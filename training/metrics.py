"""Segmentation metrics, accumulated over a whole split rather than averaged.

Per-batch metrics averaged across batches are subtly wrong for segmentation:
a batch containing three pixels of the strong class produces an IoU for that
class computed from three pixels, and averaging it with a batch of a hundred
thousand gives the three-pixel estimate equal say. So everything here is
derived from a single confusion matrix accumulated over the entire split, and
the per-class figures are computed once at the end from real totals.

Classes that never appear and are never predicted are reported as ``None``
rather than 0. An IoU of 0 means "predicted this class and got it wrong"; an
absent class means "there was nothing to get right". Collapsing the two is how
a mean IoU ends up quietly dragged down by a class the split does not contain.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from preprocessing.baseline import CLASS_NAMES, NUM_CLASSES


@dataclass
class ClassMetrics:
    """Per-class figures, all derived from the confusion matrix."""

    index: int
    name: str
    support: int
    """True pixels of this class in the split."""

    predicted: int
    iou: float | None
    dice: float | None
    precision: float | None
    recall: float | None


class ConfusionMatrix:
    """Accumulates true-vs-predicted pixel counts across a split."""

    def __init__(self, num_classes: int = NUM_CLASSES, ignore_index: int = -100) -> None:
        self.num_classes = num_classes
        self.ignore_index = ignore_index
        self.matrix = np.zeros((num_classes, num_classes), dtype=np.int64)

    def update(self, targets, predictions) -> None:
        """Accumulate one batch. Accepts torch tensors or numpy arrays."""
        true = _to_numpy(targets).reshape(-1)
        pred = _to_numpy(predictions).reshape(-1)
        if true.shape != pred.shape:
            raise ValueError(
                f"Targets and predictions differ in size: {true.shape} vs {pred.shape}"
            )
        valid = (true != self.ignore_index) & (true >= 0) & (true < self.num_classes)
        true = true[valid]
        pred = np.clip(pred[valid], 0, self.num_classes - 1)
        # bincount on the flattened (true, pred) index is the fast, exact way
        # to build the matrix; np.add.at would be an order of magnitude slower
        # at 512x512 per image.
        flat = true.astype(np.int64) * self.num_classes + pred.astype(np.int64)
        self.matrix += np.bincount(
            flat, minlength=self.num_classes**2
        ).reshape(self.num_classes, self.num_classes)

    # -- derived figures ------------------------------------------------

    def per_class(self) -> list[ClassMetrics]:
        out: list[ClassMetrics] = []
        for c in range(self.num_classes):
            tp = int(self.matrix[c, c])
            support = int(self.matrix[c].sum())
            predicted = int(self.matrix[:, c].sum())
            union = support + predicted - tp
            out.append(
                ClassMetrics(
                    index=c,
                    name=CLASS_NAMES.get(c, str(c)),
                    support=support,
                    predicted=predicted,
                    iou=(tp / union) if union else None,
                    dice=(2 * tp / (support + predicted)) if (support + predicted) else None,
                    precision=(tp / predicted) if predicted else None,
                    recall=(tp / support) if support else None,
                )
            )
        return out

    def pixel_accuracy(self) -> float:
        total = int(self.matrix.sum())
        return float(np.trace(self.matrix) / total) if total else 0.0

    def mean_iou(self) -> float:
        values = [m.iou for m in self.per_class() if m.iou is not None]
        return float(np.mean(values)) if values else 0.0

    def mean_dice(self) -> float:
        values = [m.dice for m in self.per_class() if m.dice is not None]
        return float(np.mean(values)) if values else 0.0

    def tissue_mean_iou(self) -> float:
        """Mean IoU excluding class 0.

        Background is both the easiest class and often the largest, so a mean
        IoU that includes it flatters the model. This is the number to read.
        """
        values = [m.iou for m in self.per_class()[1:] if m.iou is not None]
        return float(np.mean(values)) if values else 0.0

    def summary(self) -> dict:
        return {
            "pixel_accuracy": round(self.pixel_accuracy(), 5),
            "mean_iou": round(self.mean_iou(), 5),
            "mean_dice": round(self.mean_dice(), 5),
            "tissue_mean_iou": round(self.tissue_mean_iou(), 5),
            "per_class": [
                {
                    "index": m.index,
                    "name": m.name,
                    "support": m.support,
                    "predicted": m.predicted,
                    "iou": _round(m.iou),
                    "dice": _round(m.dice),
                    "precision": _round(m.precision),
                    "recall": _round(m.recall),
                }
                for m in self.per_class()
            ],
            "confusion_matrix": self.matrix.tolist(),
        }

    # -- artifacts -------------------------------------------------------

    def write_json(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.summary(), fh, indent=2)

    def write_csv(self, path: str | Path) -> None:
        """Per-class metrics as a CSV, for reading without a JSON viewer."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                ["index", "name", "support", "predicted", "iou", "dice",
                 "precision", "recall"]
            )
            for m in self.per_class():
                writer.writerow(
                    [m.index, m.name, m.support, m.predicted,
                     _round(m.iou), _round(m.dice), _round(m.precision), _round(m.recall)]
                )

    def write_confusion_csv(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        names = [CLASS_NAMES.get(c, str(c)) for c in range(self.num_classes)]
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["true \\ predicted", *names])
            for c, name in enumerate(names):
                writer.writerow([name, *self.matrix[c].tolist()])

    def format_table(self) -> str:
        lines = [
            f"{'class':<16}{'support':>12}{'IoU':>9}{'Dice':>9}"
            f"{'prec':>9}{'recall':>9}"
        ]
        for m in self.per_class():
            lines.append(
                f"{m.name:<16}{m.support:>12,}"
                f"{_fmt(m.iou):>9}{_fmt(m.dice):>9}"
                f"{_fmt(m.precision):>9}{_fmt(m.recall):>9}"
            )
        lines.append(
            f"pixel acc {self.pixel_accuracy():.4f}   mIoU {self.mean_iou():.4f}   "
            f"tissue mIoU {self.tissue_mean_iou():.4f}"
        )
        return "\n".join(lines)


def _to_numpy(value) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value)


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 5)


def _fmt(value: float | None) -> str:
    return "  n/a" if value is None else f"{value:.4f}"
