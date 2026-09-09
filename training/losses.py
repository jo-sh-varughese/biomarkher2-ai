"""Segmentation losses, and the class-imbalance problem they exist to fight.

The class distribution here is not mildly skewed, it is extreme. On a typical
HER2 patch most tissue pixels are unstained cytoplasm and stroma; the strongly
stained membrane pixels that decide the score can be a few percent of the
frame, and on a 0-score patch they are absent entirely. Plain cross-entropy
optimises average per-pixel correctness, and the cheapest way to a low average
is to never predict the rare classes at all. A model that does that reports a
respectable pixel accuracy and is clinically useless -- it cannot see the
thing it was built to measure.

So the default loss is cross-entropy **plus** soft Dice. Dice is computed per
class and averaged over classes, which makes a rare class count as much as a
common one, and its gradient does not vanish when a class is a small fraction
of the pixels.

Two details that matter and are easy to get wrong:

* **Absent classes are excluded from the Dice average**, not scored as 0 or 1.
  A 0-score patch contains no strong-staining pixels; a model that correctly
  predicts none should be neither rewarded nor punished for that class, and
  averaging in a fixed value for it would move the loss for reasons unrelated
  to the prediction.

* **Ignored pixels are masked out of both terms.** ``ignore_index`` exists so
  that regions we have no honest label for -- should any arise, e.g. from
  future partial annotation -- contribute nothing rather than contributing a
  guess.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class LossBreakdown:
    """The total and its parts, so a training log can show which is moving."""

    total: torch.Tensor
    cross_entropy: torch.Tensor
    dice: torch.Tensor
    focal: torch.Tensor

    def item(self) -> dict[str, float]:
        return {
            "loss": float(self.total.detach()),
            "loss_ce": float(self.cross_entropy.detach()),
            "loss_dice": float(self.dice.detach()),
            "loss_focal": float(self.focal.detach()),
        }


def soft_dice_loss(
    logits: torch.Tensor,
    targets: torch.Tensor,
    num_classes: int,
    ignore_index: int = -100,
    smooth: float = 1.0,
) -> torch.Tensor:
    """1 - mean Dice over the classes actually present in ``targets``.

    ``logits`` is NxCxHxW, ``targets`` is NxHxW of class indices.
    """
    if logits.ndim != 4:
        raise ValueError(f"Expected NxCxHxW logits, got {tuple(logits.shape)}")
    if targets.shape != (logits.shape[0], *logits.shape[2:]):
        raise ValueError(
            f"Target shape {tuple(targets.shape)} does not match logits "
            f"{tuple(logits.shape)}"
        )

    probs = logits.softmax(dim=1)
    valid = targets != ignore_index
    # Ignored pixels are zeroed in both the prediction and the target, so they
    # contribute to neither the intersection nor the union.
    safe_targets = torch.where(valid, targets, torch.zeros_like(targets))
    one_hot = F.one_hot(safe_targets.long(), num_classes).permute(0, 3, 1, 2).float()
    mask = valid.unsqueeze(1).float()
    probs = probs * mask
    one_hot = one_hot * mask

    dims = (0, 2, 3)
    intersection = (probs * one_hot).sum(dims)
    cardinality = probs.sum(dims) + one_hot.sum(dims)
    dice = (2.0 * intersection + smooth) / (cardinality + smooth)

    present = one_hot.sum(dims) > 0
    if not bool(present.any()):
        return logits.sum() * 0.0
    return 1.0 - dice[present].mean()


def focal_loss(
    logits: torch.Tensor,
    targets: torch.Tensor,
    gamma: float = 2.0,
    ignore_index: int = -100,
    weight: torch.Tensor | None = None,
) -> torch.Tensor:
    """Focal loss (Lin et al., 2017, "Focal Loss for Dense Object Detection").

    ``logits`` is NxCxHxW, ``targets`` is NxHxW of class indices. Downweights
    the loss contribution of pixels the model already assigns high
    probability to their true class -- background and negative, which
    dominate every patch here by sheer pixel count -- so gradient is not
    drowned out by pixels that were never going to be hard.

    The modulating factor ``(1 - p_t)^gamma`` and the optional class weight
    are computed under ``torch.no_grad()`` and applied as a per-pixel
    multiplier on the (still-differentiable) plain cross-entropy term --
    the standard construction, and deliberately so: backpropagating through
    the modulating factor itself would double-count exactly the effect it
    exists to apply once.
    """
    if logits.ndim != 4:
        raise ValueError(f"Expected NxCxHxW logits, got {tuple(logits.shape)}")
    ce = F.cross_entropy(logits, targets, ignore_index=ignore_index, reduction="none")
    valid = targets != ignore_index
    if not bool(valid.any()):
        return logits.sum() * 0.0

    with torch.no_grad():
        p_t = torch.exp(-ce)
        focal_term = (1.0 - p_t) ** gamma
        if weight is not None:
            # clamp: ignore_index (-100) is not a valid index into `weight`;
            # the pixels it would touch are dropped by `valid` right after.
            alpha_t = weight[targets.clamp(min=0)]
        else:
            alpha_t = torch.ones_like(p_t)

    return (alpha_t[valid] * focal_term[valid] * ce[valid]).mean()


class SegmentationLoss(nn.Module):
    """Weighted sum of cross-entropy, soft Dice, and (optionally) focal loss."""

    def __init__(self, config, num_classes: int) -> None:
        super().__init__()
        self.num_classes = num_classes
        self.ce_weight = float(config.cross_entropy_weight)
        self.dice_weight = float(config.dice_weight)
        self.focal_weight = float(getattr(config, "focal_weight", 0.0))
        self.focal_gamma = float(getattr(config, "focal_gamma", 2.0))
        self.ignore_index = int(config.ignore_index)
        self.dice_smooth = float(config.dice_smooth)
        self.label_smoothing = float(config.label_smoothing)

        weights = config.class_weights
        if isinstance(weights, str):
            # "auto" is resolved by training.train.resolve_class_weights, which
            # needs the fit set to count. Reaching here with a string means the
            # loss was built without it -- fail loudly rather than silently
            # training unweighted after the config asked for weights.
            raise ValueError(
                f"class_weights is still {weights!r}; call "
                "training.train.resolve_class_weights before building the loss"
            )
        if weights is not None:
            if len(weights) != num_classes:
                raise ValueError(
                    f"class_weights has {len(weights)} entries but there are "
                    f"{num_classes} classes"
                )
            # Registered as a buffer so it follows the module across devices
            # and is saved with the checkpoint -- a loss reproduced with
            # different weights is a different experiment.
            self.register_buffer("class_weights", torch.tensor(weights, dtype=torch.float32))
        else:
            self.class_weights = None

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> LossBreakdown:
        targets = targets.long()
        ce = F.cross_entropy(
            logits,
            targets,
            weight=self.class_weights,
            ignore_index=self.ignore_index,
            label_smoothing=self.label_smoothing,
        )
        if self.dice_weight > 0:
            dice = soft_dice_loss(
                logits,
                targets,
                num_classes=self.num_classes,
                ignore_index=self.ignore_index,
                smooth=self.dice_smooth,
            )
        else:
            dice = torch.zeros((), device=logits.device, dtype=logits.dtype)

        if self.focal_weight > 0:
            focal = focal_loss(
                logits,
                targets,
                gamma=self.focal_gamma,
                ignore_index=self.ignore_index,
                weight=self.class_weights,
            )
        else:
            focal = torch.zeros((), device=logits.device, dtype=logits.dtype)

        total = self.ce_weight * ce + self.dice_weight * dice + self.focal_weight * focal
        return LossBreakdown(total=total, cross_entropy=ce, dice=dice, focal=focal)


def inverse_frequency_weights(
    class_counts: dict[int, int], num_classes: int, floor: float = 1e-6
) -> list[float]:
    """Class weights proportional to 1/frequency, normalised to mean 1.

    Offered as a helper rather than applied by default. Inverse-frequency
    weighting on a distribution this skewed can push the loss to chase a class
    that occupies a fraction of a percent of the pixels, which destabilises
    training; whether it helps is an empirical question for a run to answer,
    not something to switch on silently.
    """
    total = sum(class_counts.get(c, 0) for c in range(num_classes))
    if total == 0:
        raise ValueError("Cannot derive weights from empty class counts.")
    freqs = [max(class_counts.get(c, 0) / total, floor) for c in range(num_classes)]
    raw = [1.0 / f for f in freqs]
    mean = sum(raw) / len(raw)
    return [w / mean for w in raw]
