"""Plot the Phase 2 training artifacts.

    python scripts/plot_training.py --run artifacts/phase2

Reads only files the run wrote -- epoch_log.csv and val_metrics_best.json --
so the plots can be regenerated later without rerunning anything, and so a
disagreement between plot and log is impossible.

Every figure carries the validation-leakage caveat in its subtitle. A curve
lifted out of this directory and pasted into a report would otherwise arrive
without it, which is precisely how an optimistic number becomes a claim.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from preprocessing.baseline import CLASS_NAMES, NUM_CLASSES
from training.splits import VAL_LEAKAGE_CAVEAT

CAVEAT_SHORT = (
    "Validation is a random draw from the training directory, not a held-out "
    "set -- these numbers are optimistic."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="artifacts/phase2")
    return parser.parse_args()


def read_log(path: Path) -> list[dict[str, float]]:
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"{path} has no epochs in it.")
    return [{k: (float(v) if v not in ("", None) else float("nan")) for k, v in r.items()}
            for r in rows]


def plot_curves(rows: list[dict[str, float]], out: Path) -> None:
    epochs = [r["epoch"] for r in rows]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))

    axes[0].plot(epochs, [r["train_loss"] for r in rows], "o-", label="train")
    axes[0].plot(epochs, [r["val_loss"] for r in rows], "s-", label="validation")
    axes[0].set_title("total loss")
    axes[0].legend(fontsize=8)

    axes[1].plot(epochs, [r["train_loss_ce"] for r in rows], "o-", label="cross-entropy")
    axes[1].plot(epochs, [r["train_loss_dice"] for r in rows], "s-", label="dice")
    axes[1].set_title("training loss components")
    axes[1].legend(fontsize=8)

    # Both means are drawn together because the gap between them is the point:
    # mean IoU includes the large, easy background class, so it sits well
    # above the figure that reflects the classes the tool exists to measure.
    axes[2].plot(epochs, [r["val_mean_iou"] for r in rows], "o-", label="mean IoU (all)")
    axes[2].plot(
        epochs, [r["val_tissue_mean_iou"] for r in rows], "s-",
        label="tissue mean IoU (classes 1-4)",
    )
    axes[2].plot(
        epochs, [r["val_pixel_accuracy"] for r in rows], "^-", label="pixel accuracy",
        alpha=0.6,
    )
    axes[2].set_title("validation metrics")
    axes[2].set_ylim(0, 1)
    axes[2].legend(fontsize=8)

    for ax in axes:
        ax.set_xlabel("epoch")
        ax.grid(alpha=0.3)
        ax.set_xticks(epochs)

    fig.suptitle("Phase 2 training", fontsize=12)
    fig.text(0.5, 0.005, CAVEAT_SHORT, ha="center", fontsize=8, style="italic")
    fig.tight_layout(rect=(0, 0.045, 1, 0.95))
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"Wrote {out}")


def plot_confusion(summary: dict, out: Path) -> None:
    matrix = np.array(summary["confusion_matrix"], dtype=np.float64)
    row_totals = matrix.sum(axis=1, keepdims=True)
    # Row-normalised: raw counts are dominated by background and show nothing.
    normalized = np.divide(matrix, row_totals, out=np.zeros_like(matrix),
                           where=row_totals > 0)

    fig, ax = plt.subplots(figsize=(7, 6))
    image = ax.imshow(normalized, cmap="Blues", vmin=0, vmax=1)
    names = [CLASS_NAMES[c] for c in range(NUM_CLASSES)]
    ax.set_xticks(range(NUM_CLASSES), names, rotation=35, ha="right", fontsize=8)
    ax.set_yticks(range(NUM_CLASSES), names, fontsize=8)
    ax.set_xlabel("predicted")
    ax.set_ylabel("pseudo-label (DAB threshold)")

    for i in range(NUM_CLASSES):
        for j in range(NUM_CLASSES):
            if row_totals[i] == 0:
                continue
            ax.text(
                j, i, f"{normalized[i, j] * 100:.1f}%",
                ha="center", va="center", fontsize=8,
                color="white" if normalized[i, j] > 0.55 else "#222222",
            )
    fig.colorbar(image, ax=ax, fraction=0.046, label="fraction of the true class")
    ax.set_title("Validation confusion matrix (row-normalised)", fontsize=11)
    fig.text(
        0.5, 0.01,
        "Rows are DAB-threshold pseudo-labels, not pathologist annotations.\n"
        + CAVEAT_SHORT,
        ha="center", fontsize=7.5, style="italic",
    )
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"Wrote {out}")


def plot_per_class(summary: dict, out: Path) -> None:
    per_class = summary["per_class"]
    names = [c["name"] for c in per_class]
    positions = np.arange(len(names))
    width = 0.38

    fig, ax = plt.subplots(figsize=(8, 4.5))
    for offset, key, colour in ((-width / 2, "iou", "#3b6ea5"), (width / 2, "dice", "#e08214")):
        values = [c[key] if c[key] is not None else 0.0 for c in per_class]
        bars = ax.bar(positions + offset, values, width, label=key.upper(), color=colour)
        for bar, entry in zip(bars, per_class):
            if entry[key] is None:
                # Absent classes are labelled, not drawn as a zero -- "not
                # present" and "got it entirely wrong" are different findings.
                ax.text(bar.get_x() + bar.get_width() / 2, 0.02, "absent",
                        ha="center", fontsize=7, rotation=90, color="#777777")

    ax.set_xticks(positions, names, rotation=20, ha="right", fontsize=9)
    ax.set_ylim(0, 1)
    ax.set_ylabel("score")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=8)
    ax.set_title("Per-class validation IoU and Dice", fontsize=11)
    fig.text(0.5, 0.01, CAVEAT_SHORT, ha="center", fontsize=8, style="italic")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"Wrote {out}")


def main() -> int:
    args = parse_args()
    run = Path(args.run)

    rows = read_log(run / "epoch_log.csv")
    plot_curves(rows, run / "training_curves.png")

    best_path = run / "val_metrics_best.json"
    if best_path.is_file():
        summary = json.loads(best_path.read_text(encoding="utf-8"))
        plot_confusion(summary, run / "val_confusion_best.png")
        plot_per_class(summary, run / "val_per_class_best.png")
    else:
        print(f"No {best_path}; skipping the per-class figures.")

    print(f"\nCAVEAT: {VAL_LEAKAGE_CAVEAT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
