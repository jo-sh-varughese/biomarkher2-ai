"""Training and evaluation engine for the multi-task U-Net (see models/multitask.py).

Built for a rented GPU on a fixed budget (the whole programme has $6.72):

* every per-pixel step runs on the GPU (training/gpu_ops.py);
* mixed precision (bf16 where supported, else fp16 with loss scaling);
* a checkpoint after every epoch, and ``resume`` picks it up, so a crash or a
  stopped pod loses minutes, not money;
* ``max_minutes`` is a hard wall-clock cap: training stops early rather than
  run past the time that was paid for, and evaluation still happens;
* throughput (tiles/s) and estimated spend are logged from the first steps,
  so a slow GPU can be spotted and swapped within minutes.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch
import torch.nn.functional as F

from evaluation.score_metrics import score_metrics
from models.multitask import HER2MultiTask, build_multitask
from training import gpu_ops
from training.losses import SegmentationLoss
from training.v2_data import ImageDataset, Sample, balanced_sampler, collate

TILE = 512
VIEW = 1024

DEFAULT_SEG_LOSS = dict(
    cross_entropy_weight=1.0, dice_weight=0.5, focal_weight=1.0, focal_gamma=2.0,
    ordinal_weight=0.0, ignore_index=-100, label_smoothing=0.0, dice_smooth=1.0, class_weights=None,
)


# --------------------------------------------------------------------------
# Batch preparation (GPU)
# --------------------------------------------------------------------------


def _views(image_u8: torch.Tensor, view: str, device) -> torch.Tensor:
    """One decoded image -> (V, 3, 1024, 1024) float views at 40x-equivalent scale."""
    x = image_u8.to(device, non_blocking=True).float().div_(255.0)[None]
    if view == "native":
        if x.shape[-1] != VIEW or x.shape[-2] != VIEW:
            x = F.interpolate(x, size=(VIEW, VIEW), mode="bilinear", align_corners=False)
        return x
    if view == "crop2x":
        return F.interpolate(x, size=(VIEW, VIEW), mode="bicubic", align_corners=False).clamp_(0, 1)
    if view == "quad2x":
        h, w = x.shape[-2:]
        quads = [x[..., y:y + h // 2, xx:xx + w // 2] for y in (0, h // 2) for xx in (0, w // 2)]
        return F.interpolate(torch.cat(quads), size=(VIEW, VIEW), mode="bicubic", align_corners=False).clamp_(0, 1)
    raise ValueError(f"Unknown view {view!r}")


def prepare_batch(batch: dict, device, prep, aug: dict | None, site_norm: dict | None = None, need_seg_labels: bool = True):
    """Collated CPU batch -> model-ready tiles.

    Returns (pixels (T,4,512,512), bag_sizes, seg_targets (T,512,512) or None).
    Pseudo-labels are computed from the un-augmented view; geometric
    augmentation is then applied to image and labels together, stain
    augmentation to the image only.
    """
    tiles, targets, bag_sizes = [], [], []
    for image, view, has_seg, site in zip(batch["images"], batch["view"], batch["has_seg"].tolist(), batch["site"]):
        v = _views(image, view, device)
        if site_norm and site in site_norm:
            v = gpu_ops.normalize_to_site(v, *site_norm[site])
        labels = gpu_ops.pseudo_labels(v, prep.tissue, prep.stain) if (has_seg and need_seg_labels) else None
        if aug:
            out_v, out_l = [], []
            for i in range(v.shape[0]):
                vi = v[i:i + 1]
                li = labels[i:i + 1] if labels is not None else None
                lo, hi = aug.get("zoom", (1.0, 1.0))
                vi, li = gpu_ops.zoom(vi, li, float(np.random.uniform(lo, hi)), VIEW)
                vi, li = gpu_ops.flip_rotate(vi, li)
                out_v.append(vi)
                out_l.append(li)
            v = torch.cat(out_v)
            labels = torch.cat(out_l) if labels is not None else None
            if aug.get("stain"):
                v = gpu_ops.stain_augment(v, aug["stain"])
            if aug.get("colour"):
                v = gpu_ops.colour_augment(v, aug["colour"])
            if aug.get("scanner"):
                v = gpu_ops.blur_noise_resample(v, aug["scanner"])
        t = gpu_ops.to_tiles(v, TILE)
        tiles.append(t)
        bag_sizes.append(t.shape[0])
        if labels is not None:
            targets.append(gpu_ops.label_tiles(labels, TILE))
        else:
            targets.append(torch.full((t.shape[0], TILE, TILE), -100, dtype=torch.long, device=device))
    pixels = gpu_ops.model_input(torch.cat(tiles))
    seg = torch.cat(targets)
    return pixels, bag_sizes, (seg if bool((seg != -100).any()) else None)


# --------------------------------------------------------------------------
# Loss
# --------------------------------------------------------------------------


class MultiTaskLoss(torch.nn.Module):
    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self.score_weight = float(cfg.get("score_weight", 1.0))
        self.seg_weight = float(cfg.get("seg_weight", 0.5))
        self.ordinal_weight = float(cfg.get("ordinal_weight", 0.2))
        self.label_smoothing = float(cfg.get("label_smoothing", 0.05))
        self.seg = SegmentationLoss(SimpleNamespace(**{**DEFAULT_SEG_LOSS, **cfg.get("seg", {})}), num_classes=5)

    def forward(self, out: dict, labels: torch.Tensor, seg_targets: torch.Tensor | None) -> tuple[torch.Tensor, dict]:
        logits = out["score_logits"].float()
        ce = F.cross_entropy(logits, labels, label_smoothing=self.label_smoothing)
        ordinal = (HER2MultiTask.expected_score(logits) - labels.float()).abs().mean()
        total = self.score_weight * (ce + self.ordinal_weight * ordinal)
        parts = {"score_ce": float(ce.detach()), "score_ordinal": float(ordinal.detach())}
        if seg_targets is not None and out["seg_logits"] is not None and self.seg_weight > 0:
            seg = self.seg(out["seg_logits"].float(), seg_targets).total
            total = total + self.seg_weight * seg
            parts["seg"] = float(seg.detach())
        parts["total"] = float(total.detach())
        return total, parts


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------


@torch.no_grad()
def predict(model: HER2MultiTask, samples: list[Sample], device, prep, batch_size: int, workers: int,
            site_norm: dict | None = None, seg_stats: bool = False, amp_dtype=None) -> list[dict]:
    """Per-sample predictions (no augmentation). Optionally pseudo-label agreement of the seg head."""
    model.eval()
    loader = torch.utils.data.DataLoader(ImageDataset(samples, train=False), batch_size=batch_size, shuffle=False,
                                         num_workers=workers, collate_fn=collate, pin_memory=device.type == "cuda")
    rows = []
    for batch in loader:
        pixels, bag_sizes, seg_targets = prepare_batch(batch, device, prep, aug=None, site_norm=site_norm, need_seg_labels=seg_stats)
        with torch.autocast(device.type, dtype=amp_dtype, enabled=amp_dtype is not None):
            out = model(pixels.contiguous(memory_format=torch.channels_last), bag_sizes, with_seg=seg_stats and seg_targets is not None)
        probs = F.softmax(out["score_logits"].float(), dim=-1).cpu().numpy()
        seg_pred = out["seg_logits"].argmax(1) if out["seg_logits"] is not None else None
        offsets = np.cumsum([0] + bag_sizes)
        for i in range(len(bag_sizes)):
            row = {"path": batch["path"][i], "site": batch["site"][i], "label": int(batch["label"][i]),
                   "slide_label": int(batch["slide_label"][i]), "pred": int(probs[i].argmax()),
                   "probs": probs[i].round(4).tolist(), "expected": float((probs[i] * np.arange(4)).sum()),
                   "attention_max": float(out["attention"][i].max())}
            if seg_pred is not None and seg_targets is not None:
                p = seg_pred[offsets[i]:offsets[i + 1]]
                t = seg_targets[offsets[i]:offsets[i + 1]]
                valid = t != -100
                row["seg_pixel_agreement"] = float((p[valid] == t[valid]).float().mean()) if valid.any() else None
            rows.append(row)
    return rows


def summarize(rows: list[dict], label_key: str = "label") -> dict:
    return score_metrics([r[label_key] for r in rows], [r["pred"] for r in rows])


# --------------------------------------------------------------------------
# Training
# --------------------------------------------------------------------------


def _amp_dtype(device):
    if device.type != "cuda":
        return None
    return torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16


def _param_groups(model: HER2MultiTask, lr: float, encoder_mult: float, weight_decay: float):
    unet = model.unet
    encoder_names = ("conv1", "bn1", "layer1", "layer2", "layer3", "layer4")
    enc, rest = [], []
    for name, p in model.named_parameters():
        if not p.requires_grad:
            continue
        (enc if name.startswith("unet.") and name.split(".")[1] in encoder_names else rest).append(p)
    del unet
    return [{"params": enc, "lr": lr * encoder_mult, "base_lr": lr * encoder_mult},
            {"params": rest, "lr": lr, "base_lr": lr}]


def _lr_factor(step: int, total: int, warmup: int) -> float:
    if step < warmup:
        return (step + 1) / max(1, warmup)
    progress = (step - warmup) / max(1, total - warmup)
    return 0.5 * (1 + math.cos(math.pi * min(1.0, progress)))


def train(cfg: dict, fit_samples: list[Sample], val_sets: dict[str, list[Sample]], out_dir: Path, prep,
          device=None, log=print) -> dict:
    """Train with per-epoch validation; returns the run summary."""
    device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
    out_dir.mkdir(parents=True, exist_ok=True)
    tcfg = cfg["train"]
    if device.type != "cuda" and tcfg.get("require_gpu", True):
        raise RuntimeError("No usable GPU and train.require_gpu is true: refusing to train on CPU on a paid pod.")
    torch.manual_seed(int(cfg.get("seed", 0)))
    np.random.seed(int(cfg.get("seed", 0)))
    if device.type == "cuda":
        torch.backends.cudnn.benchmark = True
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True

    model = build_multitask(cfg["model"], weights_dir=cfg.get("weights_dir")).to(device).to(memory_format=torch.channels_last)
    criterion = MultiTaskLoss(cfg.get("loss", {})).to(device)
    optimizer = torch.optim.AdamW(_param_groups(model, float(tcfg["lr"]), float(tcfg.get("encoder_lr_mult", 0.3)),
                                                float(tcfg.get("weight_decay", 1e-4))), weight_decay=float(tcfg.get("weight_decay", 1e-4)))
    amp_dtype = _amp_dtype(device)
    scaler = torch.amp.GradScaler("cuda", enabled=amp_dtype == torch.float16)

    epochs = int(tcfg["epochs"])
    bags_per_epoch = int(tcfg["bags_per_epoch"])
    batch_bags = int(tcfg["batch_bags"])
    steps_per_epoch = max(1, bags_per_epoch // batch_bags)
    total_steps = epochs * steps_per_epoch
    warmup = int(total_steps * float(tcfg.get("warmup_fraction", 0.05)))
    max_seconds = float(tcfg.get("max_minutes", 1e9)) * 60
    price = float(cfg.get("gpu_price_per_hour", 0.0))

    state = {"epoch": 0, "step": 0, "best": -1e9, "history": []}
    last = out_dir / "last.pt"
    if tcfg.get("resume", True) and last.is_file():
        ck = torch.load(last, map_location=device, weights_only=False)
        model.load_state_dict(ck["model_state"])
        optimizer.load_state_dict(ck["optimizer_state"])
        if ck.get("scaler_state"):
            scaler.load_state_dict(ck["scaler_state"])
        state = ck["state"]
        log(f"Resumed from {last} at epoch {state['epoch']} (best {state['best']:.4f})")

    started = time.time()
    stopped_early = False
    workers = int(tcfg.get("workers", 4))
    shared = shared_space_norm(cfg)
    if shared:
        log(f"Shared stain space: sites {sorted(shared)} mapped into the reference stain space for training and validation")
    for epoch in range(state["epoch"], epochs):
        model.train()
        sampler = balanced_sampler(fit_samples, steps_per_epoch * batch_bags, seed=int(cfg.get("seed", 0)) + epoch)
        loader = torch.utils.data.DataLoader(ImageDataset(fit_samples, train=True), batch_size=batch_bags, sampler=sampler,
                                             num_workers=workers, collate_fn=collate, pin_memory=device.type == "cuda",
                                             persistent_workers=False, prefetch_factor=4 if workers else None, drop_last=True)
        # Throughput is timed from the end of the first step, so one-off costs
        # (weight download, worker start-up, cuDNN autotuning) do not make a
        # fast GPU look slow -- run.sh's throughput guard reads this number.
        t_epoch, tiles_seen, running = time.time(), 0, []
        t_rate, tiles_rate = None, 0
        for i, batch in enumerate(loader):
            factor = _lr_factor(state["step"], total_steps, warmup)
            for g in optimizer.param_groups:
                g["lr"] = g["base_lr"] * factor
            pixels, bag_sizes, seg_targets = prepare_batch(batch, device, prep, aug=cfg.get("augment"), site_norm=shared)
            labels = batch["label"].to(device)
            with torch.autocast(device.type, dtype=amp_dtype, enabled=amp_dtype is not None):
                out = model(pixels.contiguous(memory_format=torch.channels_last), bag_sizes, with_seg=seg_targets is not None)
            loss, parts = criterion(out, labels, seg_targets)
            optimizer.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), float(tcfg.get("max_grad_norm", 1.0)))
            scaler.step(optimizer)
            scaler.update()
            state["step"] += 1
            tiles_seen += pixels.shape[0]
            if t_rate is None:
                t_rate = time.time()
            else:
                tiles_rate += pixels.shape[0]
            running.append(parts)
            if (i + 1) % int(tcfg.get("log_every", 25)) == 0 or i == 0:
                el = time.time() - started
                rate = tiles_rate / max(1e-6, time.time() - t_rate)
                mean = {k: round(float(np.mean([r[k] for r in running if k in r])), 4) for k in running[-1]}
                log(f"epoch {epoch + 1}/{epochs} step {i + 1}/{steps_per_epoch} {mean} | {rate:.1f} tiles/s | "
                    f"{el / 60:.1f} min elapsed, ~${el / 3600 * price:.2f}")
                running = []
            if time.time() - started > max_seconds:
                log(f"Wall-clock cap of {tcfg.get('max_minutes')} min reached mid-epoch; stopping training.")
                stopped_early = True
                break

        t_train_end = time.time()
        # ---- validation ----
        val = {}
        for name, samples in val_sets.items():
            rows = predict(model, samples, device, prep, int(tcfg.get("eval_batch", 4)), workers, site_norm=shared, amp_dtype=amp_dtype)
            val[name] = summarize(rows)
        selection = float(np.mean([v["qwk"] for v in val.values()])) if val else -float(loss)
        record = {"epoch": epoch + 1, "selection_mean_qwk": selection, "minutes": (time.time() - started) / 60,
                  "epoch_tiles_per_s": tiles_rate / max(1e-6, (t_train_end or time.time()) - (t_rate or t_epoch)),
                  **{f"{n}_{k}": round(v[k], 4) for n, v in val.items() for k in ("accuracy", "balanced_accuracy", "qwk")}}
        state["history"].append(record)
        log(json.dumps(record))
        state["epoch"] = epoch + 1
        checkpoint = {"model_state": model.state_dict(), "model_config": model.config, "config": cfg,
                      "optimizer_state": optimizer.state_dict(), "scaler_state": scaler.state_dict(), "state": state}
        if selection > state["best"]:
            state["best"] = selection
            checkpoint["state"] = state
            torch.save({k: checkpoint[k] for k in ("model_state", "model_config", "config", "state")}, out_dir / "best.pt")
            log(f"  new best (mean val QWK {selection:.4f}) -> best.pt")
        torch.save(checkpoint, last)
        (out_dir / "history.json").write_text(json.dumps(state["history"], indent=2), encoding="utf-8")
        if stopped_early:
            break
        epoch_seconds = (time.time() - started) / max(1, len(state["history"]))
        if time.time() - started + epoch_seconds > max_seconds:
            log("Not enough wall-clock budget left for another epoch; stopping training.")
            break

    summary = {"epochs_completed": state["epoch"], "best_mean_val_qwk": state["best"],
               "minutes": (time.time() - started) / 60, "estimated_cost_usd": (time.time() - started) / 3600 * price,
               "device": str(device), "amp": str(amp_dtype), "fit_samples": len(fit_samples),
               "val_samples": {k: len(v) for k, v in val_sets.items()}}
    (out_dir / "train_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def shared_space_norm(cfg: dict, root: Path | None = None) -> dict | None:
    """``data.train_site_norm: true`` -> map every non-reference site into the training reference stain space.

    One shared stain space for multi-hospital training: each extra site is
    re-rendered in HER2_IHC_40X's stain vectors and DAB scale during training
    and validation, so a new hospital later only has to be mapped into the
    same space. Returns a ``prepare_batch``-style site_norm dict, or None.
    """
    if not cfg.get("data", {}).get("train_site_norm"):
        return None
    root = root or Path(__file__).resolve().parents[1]
    profiles = json.loads((root / cfg["data"]["site_profiles"]).read_text(encoding="utf-8"))
    return {"bci": (profiles["bci_crop2x"], profiles["source"])}


def load_model(checkpoint: Path, device) -> HER2MultiTask:
    ck = torch.load(checkpoint, map_location="cpu", weights_only=False)
    cfg = dict(ck["model_config"])
    weights = cfg.get("encoder_weights")
    cfg["encoder_weights"] = None  # weights come from the checkpoint; never re-download
    model = build_multitask(cfg)
    if weights:
        # restore the RGB statistics the encoder was trained with
        from models.unet_seg import rgb_statistics

        mean, std = rgb_statistics(weights)
        model.rgb_mean = torch.tensor(mean).view(1, 3, 1, 1)
        model.rgb_std = torch.tensor(std).view(1, 3, 1, 1)
        model.config["encoder_weights"] = weights
    model.load_state_dict(ck["model_state"])
    return model.to(device).to(memory_format=torch.channels_last).eval()


def as_dict(samples: list[Sample]) -> list[dict]:
    return [asdict(s) for s in samples]
