"""Site-Adaptive HER2 Calibration: label-free adaptation to a new hospital.

Stages 3 and 4 of the approach in docs/V2_TRAINING_PLAN.md ("research"
section). Both use only UNLABELLED images from the new site; target labels
are never read (target samples are built with label = -1).

Stage 3 -- BatchNorm adaptation (after FUSION, Chattopadhyay et al. 2022)
------------------------------------------------------------------------
Re-estimate every BatchNorm layer's mean/variance on target-site tiles and
blend with the source statistics: ``stat = alpha * target + (1 - alpha) *
source``. A covariate shift shows up first in these statistics.

Stage 4 -- intensity-preserving self-training (this project's contribution)
---------------------------------------------------------------------------
Mean-teacher self-training on target images. The teacher (an EMA of the
student) labels a weakly augmented view; the student learns to give the same
answer on a strongly augmented view. Two HER2-specific choices:

* **The strong view never changes DAB strength.** Generic consistency
  training jitters intensity too, which for HER2 would teach the model that a
  3+ and a 1+ are the same picture -- DAB darkness is the label. Strong views
  change stain hue (vector rotation), haematoxylin strength, blur, noise,
  resampling and geometry only.
* **Distribution alignment** (Berthelot et al., ReMixMatch, ICLR 2020): the
  teacher's probabilities are re-weighted by (prior / running mean of its own
  predictions) before thresholding. On BCI the source model almost never
  predicted 1+; without this, self-training would entrench that bias.

A labelled SOURCE batch is mixed into every step so the score head cannot
drift away from what a 0 / 1+ / 2+ / 3+ means. After self-training, stage 3
is re-run so the final BatchNorm statistics are the target site's.
"""

from __future__ import annotations

import copy
import dataclasses
import time

import numpy as np
import torch
import torch.nn.functional as F

from models.multitask import HER2MultiTask
from training.v2_data import ImageDataset, Sample, balanced_sampler, collate
from training.v2_engine import MultiTaskLoss, _amp_dtype, prepare_batch


def unlabelled(samples: list[Sample]) -> list[Sample]:
    """Strip labels so adaptation code cannot read them, even by accident."""
    return [dataclasses.replace(s, label=-1, slide_label=-1) for s in samples]


def _bn_layers(model: torch.nn.Module):
    return [m for m in model.modules() if isinstance(m, torch.nn.modules.batchnorm._BatchNorm)]


@torch.no_grad()
def adapt_batchnorm(model: HER2MultiTask, target: list[Sample], device, prep, *, alpha: float = 1.0,
                    max_bags: int = 512, batch_bags: int = 8, workers: int = 4, site_norm: dict | None = None,
                    amp_dtype=None) -> dict:
    """Stage 3: blend BatchNorm running statistics toward the target site."""
    layers = _bn_layers(model)
    source = [(m.running_mean.clone(), m.running_var.clone(), m.momentum) for m in layers]
    for m in layers:
        m.reset_running_stats()
        m.momentum = None  # cumulative average over all target batches
    model.eval()
    for m in layers:
        m.train()
    loader = torch.utils.data.DataLoader(ImageDataset(target[:max_bags], train=False), batch_size=batch_bags,
                                         shuffle=False, num_workers=workers, collate_fn=collate)
    seen = 0
    for batch in loader:
        pixels, bags, _ = prepare_batch(batch, device, prep, aug=None, site_norm=site_norm, need_seg_labels=False)
        with torch.autocast(device.type, dtype=amp_dtype, enabled=amp_dtype is not None):
            model(pixels.contiguous(memory_format=torch.channels_last), bags, with_seg=True)
        seen += len(bags)
    for m, (mean, var, momentum) in zip(layers, source):
        m.running_mean.mul_(alpha).add_(mean * (1 - alpha))
        m.running_var.mul_(alpha).add_(var * (1 - alpha))
        m.momentum = momentum
    model.eval()
    return {"bn_layers": len(layers), "target_bags": seen, "alpha": alpha}


class DistributionAlignment:
    """Running mean of teacher predictions; re-weights toward a target prior."""

    def __init__(self, num_classes: int = 4, prior=None, momentum: float = 0.99) -> None:
        self.prior = torch.tensor(prior if prior is not None else [1.0 / num_classes] * num_classes)
        self.running = self.prior.clone()
        self.momentum = momentum

    def __call__(self, probs: torch.Tensor) -> torch.Tensor:
        self.running = self.momentum * self.running + (1 - self.momentum) * probs.detach().float().mean(0).cpu()
        ratio = (self.prior / self.running.clamp_min(1e-6)).to(probs.device)
        aligned = probs * ratio
        return aligned / aligned.sum(-1, keepdim=True)


def intensity_preserving(aug: dict) -> dict:
    """The strong view: everything in ``aug`` except DAB-strength changes."""
    out = copy.deepcopy(aug)
    if "stain" in out:
        out["stain"]["dab_scale"] = (1.0, 1.0)
    if "colour" in out:
        out["colour"]["brightness"] = min(0.03, float(out["colour"].get("brightness", 0.0)))
    return out


def self_train(model: HER2MultiTask, source: list[Sample], target: list[Sample], device, prep, cfg: dict,
               site_norm: dict | None = None, log=print) -> dict:
    """Stage 4: intensity-preserving mean-teacher self-training. Returns training stats."""
    if any(s.label != -1 for s in target):
        raise ValueError("Target samples must be unlabelled (use site_adapt.unlabelled).")
    scfg = cfg["self_train"]
    amp_dtype = _amp_dtype(device)
    teacher = copy.deepcopy(model).eval()
    for p in teacher.parameters():
        p.requires_grad_(False)
    criterion = MultiTaskLoss(cfg.get("loss", {})).to(device)
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=float(scfg["lr"]),
                                  weight_decay=float(scfg.get("weight_decay", 1e-4)))
    align = DistributionAlignment(prior=scfg.get("prior"))
    weak_aug = {"zoom": (1.0, 1.0)}  # flips/rotations only
    strong_aug = intensity_preserving(cfg["augment"])
    steps = int(scfg["steps"])
    tau = float(scfg.get("threshold", 0.7))
    ema = float(scfg.get("ema", 0.999))
    lam = float(scfg.get("unsup_weight", 1.0))
    workers = int(scfg.get("workers", 4))

    def loader(samples, n, bags, seed):
        return iter(torch.utils.data.DataLoader(
            ImageDataset(samples, train=True), batch_size=bags, num_workers=workers, collate_fn=collate, drop_last=True,
            sampler=torch.utils.data.RandomSampler(samples, replacement=True, num_samples=n * bags,
                                                   generator=torch.Generator().manual_seed(seed))))

    src_iter = iter(torch.utils.data.DataLoader(
        ImageDataset(source, train=True), batch_size=int(scfg.get("source_bags", 2)), num_workers=workers,
        collate_fn=collate, drop_last=True, sampler=balanced_sampler(source, steps * int(scfg.get("source_bags", 2)), seed=1)))
    tgt_iter = loader(target, steps, int(scfg.get("target_bags", 4)), seed=2)

    started, kept, history = time.time(), [], []
    model.train()
    for step in range(steps):
        sb, tb = next(src_iter), next(tgt_iter)
        # supervised source term (keeps the meaning of each score)
        px, bags, seg = prepare_batch(sb, device, prep, aug=cfg["augment"])
        with torch.autocast(device.type, dtype=amp_dtype, enabled=amp_dtype is not None):
            out = model(px.contiguous(memory_format=torch.channels_last), bags, with_seg=seg is not None)
        sup, _ = criterion(out, sb["label"].to(device), seg)
        # teacher on the weak view
        wx, wbags, _ = prepare_batch(tb, device, prep, aug=weak_aug, site_norm=site_norm, need_seg_labels=False)
        with torch.no_grad(), torch.autocast(device.type, dtype=amp_dtype, enabled=amp_dtype is not None):
            t_logits = teacher(wx.contiguous(memory_format=torch.channels_last), wbags, with_seg=False)["score_logits"]
        t_probs = align(F.softmax(t_logits.float(), -1))
        conf, pseudo = t_probs.max(-1)
        mask = (conf >= tau).float()
        t_expected = (t_probs * torch.arange(4, device=device)).sum(-1)
        # student on the strong (intensity-preserving) view
        sx, sbags, _ = prepare_batch(tb, device, prep, aug=strong_aug, site_norm=site_norm, need_seg_labels=False)
        with torch.autocast(device.type, dtype=amp_dtype, enabled=amp_dtype is not None):
            s_logits = model(sx.contiguous(memory_format=torch.channels_last), sbags, with_seg=False)["score_logits"].float()
        ce = (F.cross_entropy(s_logits, pseudo, reduction="none") * mask).sum() / mask.sum().clamp_min(1.0)
        ordinal = (HER2MultiTask.expected_score(s_logits) - t_expected).abs().mean()
        loss = sup + lam * (ce + float(scfg.get("ordinal_weight", 0.2)) * ordinal)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        with torch.no_grad():
            for pt, ps in zip(teacher.parameters(), model.parameters()):
                pt.mul_(ema).add_(ps.detach(), alpha=1 - ema)
            for bt, bs in zip(teacher.buffers(), model.buffers()):
                bt.copy_(bs)
        kept.append(float(mask.mean()))
        if (step + 1) % int(scfg.get("log_every", 50)) == 0 or step == 0:
            rec = {"step": step + 1, "sup": round(float(sup.detach()), 4), "unsup_ce": round(float(ce.detach()), 4),
                   "kept": round(float(np.mean(kept[-50:])), 3),
                   "pseudo_label_mix": [round(float(x), 3) for x in align.running.tolist()],
                   "minutes": round((time.time() - started) / 60, 2)}
            history.append(rec)
            log(f"self-train {rec}")
    model.eval()
    # Return the EMA teacher: it is the smoother of the two, and the usual choice in mean-teacher methods.
    model.load_state_dict(teacher.state_dict())
    return {"steps": steps, "mean_kept": float(np.mean(kept)), "history": history,
            "minutes": (time.time() - started) / 60}
