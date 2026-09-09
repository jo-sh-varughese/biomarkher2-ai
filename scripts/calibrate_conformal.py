"""Calibrate a conformal predictor over the reserved held-out set's
calibration half, and save the calibration artifact.

    python scripts/calibrate_conformal.py --run artifacts/phase2_unet

This is Phase 4's one spend of the held-out set training/splits.py reserves
(see PHASE2.md, "The held-out set was not touched in Phase 2"). It never
looks at fit or val, and it splits holdout itself into calibration and test
halves -- see evaluation/calibration_split.py -- so the two never overlap.

Writes ``<run>/conformal_calibration.npz`` (per-class nonconformity scores
and per-patch stain descriptors) and ``<run>/conformal_calibration_ids.json``
(exactly which patches went where, for audit, and for
scripts/evaluate_conformal.py to read back).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.calibration_split import HOLDOUT_SPLIT_CAVEAT, split_holdout_for_conformal
from evaluation.conformal import (
    PSEUDO_LABEL_CALIBRATION_CAVEAT,
    checkpoint_fingerprint,
    hinge_scores,
)
from evaluation.stain_shift import patch_stain_descriptor
from models import prepare_pixel_array, select_architecture
from preprocessing.baseline import NUM_CLASSES
from preprocessing.sources import DirectoryPatchSource
from training.config import TrainingConfig
from training.pseudo_labels import PseudoLabelCache
from training.splits import build_splits, stratified_subsample


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="artifacts/phase2_unet")
    parser.add_argument("--config", default="configs/training.yaml")
    parser.add_argument(
        "--calibration-fraction",
        type=float,
        default=0.5,
        help="Fraction of the holdout set spent on calibration; the rest "
        "becomes scripts/evaluate_conformal.py's test set.",
    )
    parser.add_argument(
        "--max-patches",
        type=int,
        default=None,
        help="Cap on calibration SOURCE PATCHES, for a smoke run, applied via "
        "training.splits.stratified_subsample -- same discipline train.py "
        "uses, and for the same reason: patch ids sort by class folder, so "
        "a plain prefix slice of the (already class-sorted) patch or tile "
        "list would smoke-test on one class only. Leave unset for a real "
        "calibration.",
    )
    parser.add_argument(
        "--max-per-class",
        type=int,
        default=20_000,
        help="Cap on calibration PIXELS kept per class, after collection. "
        "Background/negative pixels vastly outnumber weak/moderate/strong "
        "in this dataset (see PHASE2.md); an unbounded calibration set costs "
        "an unbounded sort in every downstream weighted_quantile call for no "
        "statistical benefit -- conformal prediction's coverage guarantee "
        "holds for any calibration size well above ~1/alpha, and this cap is "
        "far above that. Pass 0 to disable.",
    )
    return parser.parse_args()


def collect_calibration_scores(
    model,
    normalize_batch,
    in_channels: int,
    cache: PseudoLabelCache,
    tile_ids: list[str],
    device: str,
) -> tuple[dict[int, list[float]], dict[int, list[np.ndarray]]]:
    """Per-tissue-pixel nonconformity scores, plus one stain descriptor per tile.

    Every tissue pixel of a tile contributes its hinge score for ITS OWN
    pseudo-label class to that class's list, paired with that tile's single
    stain descriptor -- matching evaluation.conformal's calibration contract
    of "one stain descriptor per calibration score, from the patch that
    pixel came from". A tile's tissue mask is exactly ``label != 0``: the
    background class already IS the tissue detector's own output, baked into
    the cached pseudo-label at build time (see training/pseudo_labels.py),
    so it is read back rather than recomputed.
    """
    scores_by_class: dict[int, list[float]] = {c: [] for c in range(1, NUM_CLASSES)}
    descriptors_by_class: dict[int, list[np.ndarray]] = {c: [] for c in range(1, NUM_CLASSES)}

    model.eval()
    with torch.no_grad():
        for index, tile_id in enumerate(tile_ids, start=1):
            rgb, label = cache.read(tile_id)
            tissue = label != 0
            if not tissue.any():
                continue
            descriptor = patch_stain_descriptor(rgb, tissue_mask=tissue)

            # NOT pre-divided by 255 here: prepare_pixel_array's 4th (DAB)
            # channel is already in optical-density units, not 0..255, and
            # each architecture's own normalize_batch knows how to scale its
            # own channels correctly -- dividing the whole tensor here would
            # silently crush the DAB channel toward zero for the U-Net.
            array = prepare_pixel_array(rgb, in_channels)
            pixels = torch.from_numpy(np.ascontiguousarray(array))
            pixels = pixels.permute(2, 0, 1).float()[None].to(device)
            logits = model(normalize_batch(pixels))
            probs = logits.softmax(dim=1)[0].permute(1, 2, 0).cpu().numpy()

            tissue_probs = probs[tissue]
            tissue_labels = label[tissue]
            scores = hinge_scores(tissue_probs)

            for true_class in range(1, NUM_CLASSES):
                member = tissue_labels == true_class
                count = int(member.sum())
                if not count:
                    continue
                scores_by_class[true_class].extend(scores[member, true_class].tolist())
                descriptors_by_class[true_class].extend([descriptor] * count)

            if index % 50 == 0 or index == len(tile_ids):
                print(f"  [{index}/{len(tile_ids)}] {tile_id}", flush=True)

    return scores_by_class, descriptors_by_class


def main() -> int:
    args = parse_args()
    config = TrainingConfig.from_yaml(args.config)
    out_dir = Path(args.run)

    build_model, normalize_batch = select_architecture(config.model.architecture)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    checkpoint = torch.load(out_dir / "best.pt", map_location=device, weights_only=False)
    model = build_model(config.model, verbose=False).to(device)
    model.load_state_dict(checkpoint["model_state"])

    source = DirectoryPatchSource(config.data.patch_root, splits=["train", "test"])
    split = build_splits(source, config.split)
    calibration_patch_ids, test_patch_ids = split_holdout_for_conformal(
        source,
        split.holdout,
        calibration_fraction=args.calibration_fraction,
        seed=config.seed,
    )

    cache = PseudoLabelCache(config.data.cache_root)
    cached_patch_ids = [pid for pid in calibration_patch_ids if cache.tile_ids(pid)]
    missing = len(calibration_patch_ids) - len(cached_patch_ids)
    if missing:
        print(
            f"NOTE: {missing} calibration patches are not in the pseudo-label "
            f"cache at {cache.root} and are excluded."
        )
    # Capped at the PATCH level, before expanding to tiles, via the same
    # stratified_subsample every other cap in this project goes through --
    # never a prefix slice of a tile or patch list, both of which sort by
    # class folder (see training/splits.py's module docstring).
    kept_patch_ids = stratified_subsample(
        source, cached_patch_ids, cap=args.max_patches, seed=config.seed
    )
    calibration_tiles = [t for pid in kept_patch_ids for t in cache.tile_ids(pid)]
    if not calibration_tiles:
        raise SystemExit(
            "No calibration tiles found in the cache. Run "
            "scripts/build_pseudo_labels.py over the holdout patches first."
        )

    print(
        f"Calibrating on {len(calibration_tiles)} tiles from "
        f"{len(kept_patch_ids)}/{len(calibration_patch_ids)} holdout patches "
        f"assigned to calibration (test half reserved: {len(test_patch_ids)} "
        f"patches). device={device}"
    )
    print(f"CAVEAT: {HOLDOUT_SPLIT_CAVEAT}")
    print(f"CAVEAT: {PSEUDO_LABEL_CALIBRATION_CAVEAT}\n")

    scores_by_class, descriptors_by_class = collect_calibration_scores(
        model, normalize_batch, config.model.in_channels, cache, calibration_tiles, device
    )

    rng = np.random.default_rng(config.seed)
    payload: dict[str, np.ndarray] = {}
    for c in range(1, NUM_CLASSES):
        if not scores_by_class[c]:
            print(
                f"WARNING: class {c} has zero calibration pixels; prediction "
                "sets will never exclude it (see evaluation.conformal.ClassCalibration)."
            )
            continue
        scores = np.asarray(scores_by_class[c], dtype=np.float32)
        descriptors = np.asarray(descriptors_by_class[c], dtype=np.float32)
        if args.max_per_class and scores.shape[0] > args.max_per_class:
            keep = rng.choice(scores.shape[0], size=args.max_per_class, replace=False)
            scores, descriptors = scores[keep], descriptors[keep]
            print(f"class {c}: subsampled to {args.max_per_class} calibration pixels "
                  f"(of {len(scores_by_class[c])} collected)")
        payload[f"scores_{c}"] = scores
        payload[f"descriptors_{c}"] = descriptors

    calibration_path = out_dir / "conformal_calibration.npz"
    np.savez_compressed(calibration_path, **payload)

    ids_path = out_dir / "conformal_calibration_ids.json"
    with open(ids_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "calibration_patch_ids": calibration_patch_ids,
                "calibration_patch_ids_used": kept_patch_ids,
                "test_patch_ids": test_patch_ids,
                "n_calibration_tiles": len(calibration_tiles),
                "max_per_class": args.max_per_class,
                "holdout_split_caveat": HOLDOUT_SPLIT_CAVEAT,
                "pseudo_label_caveat": PSEUDO_LABEL_CALIBRATION_CAVEAT,
                # Recorded so a later caller (app.analysis.Analyzer) can tell
                # whether the checkpoint it just loaded is the same one this
                # calibration was computed against -- a checkpoint retrained
                # after calibration ran would otherwise have its probabilities
                # silently scored against someone else's quantiles.
                "checkpoint_epoch": int(checkpoint.get("epoch", -1)),
                "checkpoint_fingerprint": checkpoint_fingerprint(out_dir / "best.pt"),
            },
            fh,
            indent=2,
        )
    print(f"\nWrote {calibration_path} and {ids_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
