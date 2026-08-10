"""The Phase 2 training loop.

Everything a run produces lands in ``output_dir`` as a plain file: the resolved
config, the exact split (with its leakage caveat), a per-epoch CSV of losses
and metrics, per-class metrics and a confusion matrix per evaluation, and the
best checkpoint. No dashboard, no external service -- the artifacts are meant
to be openable a year from now by someone who no longer has this environment.

Model selection is on **tissue mean IoU**, not on validation loss and not on
overall mean IoU. Overall mIoU includes the background class, which is large
and easy, so it keeps rising while the clinically relevant classes stagnate.
Validation loss is dominated by the same majority pixels. Tissue mean IoU
weights the four staining classes equally, which is the behaviour we actually
want to select for.

The validation numbers this loop prints are NOT a generalization estimate --
see :mod:`training.splits`. The caveat is written into every artifact this
module produces so it cannot be read without it.

**This loop never evaluates the held-out set.** It resolves it, records its
size and writes its patch ids, and then does not look at it. That is
deliberate: a held-out number watched during development stops being held out,
because every decision about epochs, learning rate and loss weights starts
being made against it. The holdout is Phase 4's to spend, once.
"""

from __future__ import annotations

import csv
import json
import math
import random
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import torch

from models.segformer_seg import build_model, normalize_batch
from preprocessing.baseline import CLASS_NAMES, NUM_CLASSES
from preprocessing.sources import DirectoryPatchSource
from training.config import TrainingConfig
from training.dataset import PseudoLabelDataset, build_loader, class_pixel_counts
from training.losses import SegmentationLoss, inverse_frequency_weights
from training.metrics import ConfusionMatrix
from training.pseudo_labels import PseudoLabelCache
from training.splits import (
    HOLDOUT_CAVEAT,
    VAL_LEAKAGE_CAVEAT,
    build_splits,
    stratified_subsample,
)

EPOCH_LOG_NAME = "epoch_log.csv"
EPOCH_LOG_FIELDS = [
    "epoch",
    "train_loss",
    "train_loss_ce",
    "train_loss_dice",
    "val_loss",
    "val_pixel_accuracy",
    "val_mean_iou",
    "val_tissue_mean_iou",
    "val_mean_dice",
    "learning_rate",
    "seconds",
]


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def lr_at(step: int, total_steps: int, base_lr: float, warmup_fraction: float) -> float:
    """Linear warmup then linear decay -- the SegFormer reference schedule."""
    warmup = max(1, int(total_steps * warmup_fraction))
    if step < warmup:
        return base_lr * (step + 1) / warmup
    progress = (step - warmup) / max(1, total_steps - warmup)
    return base_lr * max(0.0, 1.0 - progress)


def evaluate(model, loader, criterion, device: str = "cpu") -> tuple[float, ConfusionMatrix]:
    """Run a split end to end, returning mean loss and an accumulated matrix."""
    model.eval()
    matrix = ConfusionMatrix(NUM_CLASSES, ignore_index=criterion.ignore_index)
    total_loss = 0.0
    batches = 0
    with torch.no_grad():
        for batch in loader:
            pixels = normalize_batch(batch["pixel_values"].to(device))
            labels = batch["labels"].to(device)
            logits = model(pixels)
            total_loss += float(criterion(logits, labels).total)
            matrix.update(labels, logits.argmax(dim=1))
            batches += 1
    return (total_loss / max(1, batches)), matrix


def train(config: TrainingConfig, verbose: bool = True) -> dict:
    """Fit the model and write every artifact. Returns the run summary."""
    set_seed(config.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    out_dir = Path(config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # -- data ----------------------------------------------------------
    source = DirectoryPatchSource(config.data.patch_root, splits=["train", "test"])
    split = build_splits(source, config.split)
    split.write(out_dir / "split.json")

    cache = PseudoLabelCache(config.data.cache_root)
    fit_ids = _available(
        source, cache, split.fit, config.data.max_fit_patches, "fit", config.seed
    )
    val_ids = _available(
        source, cache, split.val, config.data.max_val_patches, "val", config.seed
    )
    # Tiles of one source patch are near-duplicates. The split is drawn over
    # patches and only then expanded, so they cannot land on opposite sides.
    # Slide-level grouping is impossible on this dataset; this level is not.
    _assert_no_parent_overlap(cache, fit_ids, val_ids)

    folder_classes = {
        tile_id: source.label(cache.parent_of(tile_id))
        for tile_id in fit_ids + val_ids
    }
    fit_set = PseudoLabelDataset(
        cache, fit_ids, augment=config.data.augment, seed=config.seed,
        folder_classes=folder_classes,
    )
    val_set = PseudoLabelDataset(
        cache, val_ids, augment=False, folder_classes=folder_classes
    )
    fit_loader = build_loader(
        fit_set, config.optim.batch_size, shuffle=True,
        num_workers=config.optim.num_workers, seed=config.seed,
    )
    val_loader = build_loader(
        val_set, config.optim.batch_size, shuffle=False,
        num_workers=config.optim.num_workers, seed=config.seed,
    )

    counts = class_pixel_counts(cache, fit_ids, limit=min(len(fit_ids), 200))
    if verbose:
        print(f"device={device}  fit={len(fit_ids)}  val={len(val_ids)}  "
              f"holdout={len(split.holdout)}")
        total_px = sum(counts.values()) or 1
        print("Training-target class balance (sampled):")
        for c in range(NUM_CLASSES):
            print(f"  {CLASS_NAMES[c]:<16}{100 * counts.get(c, 0) / total_px:6.2f}%")
        print(f"\nCAVEAT: {VAL_LEAKAGE_CAVEAT}\n")

    resolve_class_weights(config, cache, fit_ids, verbose=verbose)

    # -- model ---------------------------------------------------------
    model = build_model(config.model, verbose=verbose).to(device)
    criterion = SegmentationLoss(config.loss, NUM_CLASSES).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.optim.learning_rate,
        weight_decay=config.optim.weight_decay,
    )

    steps_per_epoch = math.ceil(len(fit_loader) / config.optim.grad_accum_steps)
    total_steps = steps_per_epoch * config.optim.epochs
    if verbose:
        print(f"{model.trainable_parameters():,} trainable parameters; "
              f"{steps_per_epoch} optimiser steps/epoch, {total_steps} total")

    # -- fit -----------------------------------------------------------
    log_path = out_dir / EPOCH_LOG_NAME
    with open(log_path, "w", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=EPOCH_LOG_FIELDS).writeheader()

    best = {"epoch": -1, "tissue_mean_iou": -1.0}
    step = 0
    history: list[dict] = []

    for epoch in range(1, config.optim.epochs + 1):
        model.train()
        started = time.time()
        totals = {"loss": 0.0, "loss_ce": 0.0, "loss_dice": 0.0}
        batches = 0
        optimizer.zero_grad(set_to_none=True)
        current_lr = config.optim.learning_rate

        for index, batch in enumerate(fit_loader):
            pixels = normalize_batch(batch["pixel_values"].to(device))
            labels = batch["labels"].to(device)
            breakdown = criterion(model(pixels), labels)
            # Scale so that accumulated gradients average rather than sum --
            # otherwise the effective learning rate silently scales with
            # grad_accum_steps.
            (breakdown.total / config.optim.grad_accum_steps).backward()

            for key, value in breakdown.item().items():
                totals[key] += value
            batches += 1

            last = index == len(fit_loader) - 1
            if (index + 1) % config.optim.grad_accum_steps == 0 or last:
                current_lr = lr_at(
                    step, total_steps, config.optim.learning_rate,
                    config.optim.warmup_fraction,
                )
                for group in optimizer.param_groups:
                    group["lr"] = current_lr
                torch.nn.utils.clip_grad_norm_(
                    model.parameters(), config.optim.max_grad_norm
                )
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                step += 1

            if verbose and (index + 1) % 20 == 0:
                done = index + 1
                rate = (time.time() - started) / done
                print(
                    f"  epoch {epoch} [{done}/{len(fit_loader)}] "
                    f"loss={totals['loss'] / done:.4f} "
                    f"({rate:.2f}s/batch, ~{rate * (len(fit_loader) - done) / 60:.1f} "
                    "min left)",
                    flush=True,
                )

        val_loss, matrix = evaluate(model, val_loader, criterion, device)
        elapsed = time.time() - started

        row = {
            "epoch": epoch,
            "train_loss": round(totals["loss"] / max(1, batches), 5),
            "train_loss_ce": round(totals["loss_ce"] / max(1, batches), 5),
            "train_loss_dice": round(totals["loss_dice"] / max(1, batches), 5),
            "val_loss": round(val_loss, 5),
            "val_pixel_accuracy": round(matrix.pixel_accuracy(), 5),
            "val_mean_iou": round(matrix.mean_iou(), 5),
            "val_tissue_mean_iou": round(matrix.tissue_mean_iou(), 5),
            "val_mean_dice": round(matrix.mean_dice(), 5),
            "learning_rate": current_lr,
            "seconds": round(elapsed, 1),
        }
        history.append(row)
        with open(log_path, "a", newline="", encoding="utf-8") as fh:
            csv.DictWriter(fh, fieldnames=EPOCH_LOG_FIELDS).writerow(row)

        if verbose:
            print(f"\nepoch {epoch}/{config.optim.epochs}  ({elapsed:.0f}s)")
            print(f"  train {row['train_loss']:.4f}   val {row['val_loss']:.4f}")
            print(matrix.format_table())
            print()

        matrix.write_json(out_dir / f"val_metrics_epoch{epoch}.json")

        if matrix.tissue_mean_iou() > best["tissue_mean_iou"]:
            best = {"epoch": epoch, "tissue_mean_iou": matrix.tissue_mean_iou()}
            torch.save(
                {
                    "epoch": epoch,
                    "model_state": model.state_dict(),
                    "config": asdict(config),
                    "val_summary": matrix.summary(),
                    "caveat": VAL_LEAKAGE_CAVEAT,
                },
                out_dir / "best.pt",
            )
            matrix.write_csv(out_dir / "val_per_class_best.csv")
            matrix.write_confusion_csv(out_dir / "val_confusion_best.csv")
            matrix.write_json(out_dir / "val_metrics_best.json")

    summary = {
        "selected_epoch": best["epoch"],
        "selection_metric": "tissue_mean_iou (mean IoU over classes 1-4)",
        "best_val_tissue_mean_iou": round(best["tissue_mean_iou"], 5),
        "validation_caveat": VAL_LEAKAGE_CAVEAT,
        "holdout_caveat": HOLDOUT_CAVEAT,
        "what_the_targets_are": (
            "DAB optical-density threshold pseudo-labels, not pathologist "
            "annotations. Agreement with them is not evidence of clinical "
            "accuracy -- see training/pseudo_labels.py."
        ),
        "sizes": {
            "fit_tiles": len(fit_ids),
            "val_tiles": len(val_ids),
            "fit_patches": len({cache.parent_of(t) for t in fit_ids}),
            "val_patches": len({cache.parent_of(t) for t in val_ids}),
            "holdout_patches": len(split.holdout),
        },
        "device": device,
        "config": asdict(config),
        "history": history,
    }
    with open(out_dir / "run_summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    config.to_yaml(out_dir / "resolved_config.yaml")

    if verbose:
        print(f"Best epoch {best['epoch']} (tissue mIoU "
              f"{best['tissue_mean_iou']:.4f}). Artifacts in {out_dir}")
    return summary


def resolve_class_weights(
    config: TrainingConfig,
    cache: PseudoLabelCache,
    fit_ids: list[str],
    verbose: bool = True,
) -> list[float] | None:
    """Turn ``class_weights: auto`` into the concrete list it stands for.

    Counted over *every* fit tile, not a sample: the weights are part of the
    experiment's definition, and a weight derived from a noisy subsample is a
    number nobody could reproduce. The resolved list is written back onto the
    config, so ``resolved_config.yaml`` records what the loss actually used
    rather than the instruction that produced it.
    """
    weights = config.loss.class_weights
    if not isinstance(weights, str):
        return weights
    if weights.lower() != "auto":
        raise ValueError(
            f"class_weights must be a list of {NUM_CLASSES} floats, null, or "
            f'"auto" -- got {weights!r}'
        )

    counts = class_pixel_counts(cache, fit_ids)
    resolved = inverse_frequency_weights(counts, NUM_CLASSES)
    config.loss.class_weights = resolved
    if verbose:
        total = sum(counts.values()) or 1
        print("class_weights: auto -> inverse frequency over all fit tiles")
        for c in range(NUM_CLASSES):
            print(f"  {CLASS_NAMES[c]:<16}{100 * counts.get(c, 0) / total:6.2f}%"
                  f"   weight {resolved[c]:.3f}")
        print()
    return resolved


def _available(
    source,
    cache: PseudoLabelCache,
    ids: list[str],
    cap: int | None,
    name: str,
    seed: int,
) -> list[str]:
    """Keep only patches that are actually cached, and say how many were not.

    Silently training on whatever happens to be present is how a run ends up
    using a fifth of the data without anyone noticing. The cap is applied by
    :func:`~training.splits.stratified_subsample`, never by slicing -- patch
    ids sort by class folder, so a slice would take one class only.
    """
    present = [pid for pid in ids if cache.tile_ids(pid)]
    missing = len(ids) - len(present)
    if not present:
        raise FileNotFoundError(
            f"None of the {len(ids)} {name} patches are in the cache at "
            f"{cache.root}. Run scripts/build_pseudo_labels.py first."
        )
    if missing:
        print(
            f"NOTE: {missing}/{len(ids)} {name} patches are not in the pseudo-label "
            f"cache and are excluded from this run."
        )

    # Cap patches first, then expand to tiles: capping tiles directly could
    # keep a fraction of one patch's tiles, which is not wrong but makes the
    # per-patch grouping harder to reason about for no benefit.
    kept = stratified_subsample(source, present, cap, seed)
    classes = sorted({source.label(p) for p in kept})
    if len(classes) < 4:
        raise ValueError(
            f"The {name} set covers only class(es) {classes}. Refusing to run: "
            "metrics from a class-incomplete set are meaningless."
        )
    tiles = [t for pid in kept for t in cache.tile_ids(pid)]
    print(f"{name}: {len(kept)} patches -> {len(tiles)} tiles")
    return tiles


def _assert_no_parent_overlap(cache: PseudoLabelCache, left, right) -> None:
    """Raise if any source patch has tiles on both sides of the split."""
    shared = {cache.parent_of(t) for t in left} & {cache.parent_of(t) for t in right}
    if shared:
        raise ValueError(
            f"Tile leakage: {len(shared)} source patch(es) have tiles in both "
            f"the fit and validation sets, e.g. {sorted(shared)[:3]}"
        )
