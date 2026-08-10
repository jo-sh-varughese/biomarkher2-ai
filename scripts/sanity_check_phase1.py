"""Phase 1 visual and numerical sanity check.

Produces two kinds of inspectable artifact:

1. Per-patch panels (original | tissue mask | haematoxylin | DAB | intensity
   map | tile grid) for a handful of patches spanning all four classes.

2. A CSV of per-patch DAB statistics, plus an aggregate table grouped by the
   dataset's own class label.

The aggregate table is the real test. Mean tissue DAB optical density must
increase monotonically across class_0 -> class_1+ -> class_2+ -> class_3+.
If it does not, either the deconvolution is wrong or the dataset labels do
not mean what we think they mean, and every downstream number inherits the
error silently.

Usage:
    python scripts/sanity_check_phase1.py --per-class 40 --panels 2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap
from matplotlib.patches import Rectangle

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from preprocessing import (  # noqa: E402
    CLASS_NAMES,
    DirectoryPatchSource,
    PreprocessingConfig,
    PreprocessingPipeline,
)
from preprocessing.sources import FOLDER_TO_SCORE  # noqa: E402

# Colourblind-safe ordinal ramp: grey background, then a light-to-dark brown
# progression matching how DAB actually reads under the microscope.
INTENSITY_COLORS = ["#f0f0f0", "#cfd8dc", "#ffd699", "#e08214", "#8c3d04"]
INTENSITY_CMAP = ListedColormap(INTENSITY_COLORS)

# Single-colour overlay for the tissue mask. Teal reads clearly over both the
# blue of haematoxylin and the brown of DAB, and stays distinguishable under
# the common forms of colour blindness.
TISSUE_CMAP = ListedColormap(["#00897b"])

CLASS_ORDER = ["class_0", "class_1+", "class_2+", "class_3+"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        default="data/raw",
        help="Root containing the split directories.",
    )
    parser.add_argument("--splits", nargs="+", default=["test"])
    parser.add_argument(
        "--config", default="configs/preprocessing.yaml", help="Preprocessing config."
    )
    parser.add_argument("--out", default="artifacts/phase1")
    parser.add_argument(
        "--per-class",
        type=int,
        default=40,
        help="Patches per class used for the DAB statistics table.",
    )
    parser.add_argument(
        "--panels",
        type=int,
        default=2,
        help="Patches per class rendered as visual panels.",
    )
    return parser.parse_args()


def select_ids(source: DirectoryPatchSource, per_class: int) -> dict[str, list[str]]:
    """Pick an evenly-spaced sample per class, deterministically.

    Even spacing rather than random sampling keeps the artifact reproducible
    across runs without depending on a seed.
    """
    by_class: dict[str, list[str]] = {folder: [] for folder in CLASS_ORDER}
    for record in source.records():
        folder = record.path.parent.name
        if folder in by_class:
            by_class[folder].append(record.patch_id)

    selected: dict[str, list[str]] = {}
    for folder, ids in by_class.items():
        if not ids:
            selected[folder] = []
            continue
        count = min(per_class, len(ids))
        step = max(1, len(ids) // count)
        selected[folder] = ids[::step][:count]
    return selected


def render_panel(result, record, config, out_path: Path) -> None:
    """Draw the six-panel visual check for one patch."""
    fig, axes = plt.subplots(1, 6, figsize=(22, 4.2))

    axes[0].imshow(result.original)
    axes[0].set_title("original")

    # Drawn as a tint over the original rather than a bare binary image: a
    # black-and-white mask is genuinely ambiguous to read (is tissue the black
    # or the white?), and the whole point of this panel is that a reviewer can
    # tell at a glance whether the mask followed the tissue.
    axes[1].imshow(result.original)
    axes[1].imshow(
        np.ma.masked_where(~result.tissue_mask, result.tissue_mask.astype(float)),
        cmap=TISSUE_CMAP,
        vmin=0,
        vmax=1,
        alpha=0.45,
        interpolation="nearest",
    )
    axes[1].set_title(
        f"tissue mask ({result.tissue_fraction * 100:.1f}%)\n"
        "teal = kept as tissue",
        fontsize=9,
    )

    im2 = axes[2].imshow(result.hematoxylin, cmap="Blues", vmin=0, vmax=1.5)
    axes[2].set_title("haematoxylin OD")
    fig.colorbar(im2, ax=axes[2], fraction=0.046)

    im3 = axes[3].imshow(result.dab, cmap="copper_r", vmin=0, vmax=1.5)
    axes[3].set_title("DAB OD (HER2 signal)")
    fig.colorbar(im3, ax=axes[3], fraction=0.046)

    axes[4].imshow(result.intensity, cmap=INTENSITY_CMAP, vmin=0, vmax=4)
    pct = result.areas.percentages
    axes[4].set_title(
        "classical intensity map\n"
        f"neg {pct.get(1, 0):.0f}%  weak {pct.get(2, 0):.0f}%  "
        f"mod {pct.get(3, 0):.0f}%  str {pct.get(4, 0):.0f}%",
        fontsize=9,
    )

    axes[5].imshow(result.original)
    for tile in result.tiles:
        axes[5].add_patch(
            Rectangle(
                (tile.source_x, tile.source_y),
                tile.size * config.tiling.downsample,
                tile.size * config.tiling.downsample,
                fill=False,
                edgecolor="#1b9e77",
                linewidth=2,
            )
        )
    axes[5].set_title(f"tile grid ({len(result.tiles)} kept)")

    for ax in axes:
        ax.axis("off")

    folder = record.path.parent.name
    fig.suptitle(
        f"{record.path.name}    "
        f"patch label: {FOLDER_TO_SCORE.get(folder, folder)}    "
        f"source slide score: {record.slide_score or 'unknown'}",
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=90, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out)
    (out_dir / "panels").mkdir(parents=True, exist_ok=True)

    config = PreprocessingConfig.from_yaml(args.config)
    pipeline = PreprocessingPipeline(config)
    source = DirectoryPatchSource(args.data_root, splits=args.splits)
    print(f"Loaded {len(source)} patches from {args.data_root} {args.splits}")

    selected = select_ids(source, args.per_class)
    rows: list[dict] = []

    for folder in CLASS_ORDER:
        ids = selected.get(folder, [])
        print(f"  {folder:9} -> {len(ids)} patches sampled")
        for index, patch_id in enumerate(ids):
            record = source.record(patch_id)
            want_panel = index < args.panels
            result = pipeline.run(
                source.read_patch(patch_id), patch_id=patch_id, with_tiles=want_panel
            )
            row = {
                "patch_id": patch_id,
                "file": record.path.name,
                "patch_label": FOLDER_TO_SCORE.get(folder, folder),
                "slide_score": record.slide_score,
                "provenance": record.provenance,
                "tissue_fraction": result.tissue_fraction,
                **result.dab_stats,
                **result.areas.as_row(),
            }
            rows.append(row)
            if want_panel:
                safe = folder.replace("+", "p")
                render_panel(
                    result, record, config, out_dir / "panels" / f"{safe}_{index}.png"
                )

    frame = pd.DataFrame(rows)
    frame.to_csv(out_dir / "patch_statistics.csv", index=False)

    summary = (
        frame.groupby("patch_label")
        .agg(
            n=("patch_id", "count"),
            tissue_frac=("tissue_fraction", "mean"),
            dab_mean=("dab_mean", "mean"),
            dab_median=("dab_median", "mean"),
            dab_p90=("dab_p90", "mean"),
            pct_negative=("pct_negative", "mean"),
            pct_weak=("pct_weak", "mean"),
            pct_moderate=("pct_moderate", "mean"),
            pct_strong=("pct_strong", "mean"),
        )
        .reindex([FOLDER_TO_SCORE[f] for f in CLASS_ORDER])
    )
    summary.to_csv(out_dir / "class_summary.csv")

    print("\n=== Mean DAB optical density by dataset class label ===")
    print(summary.round(4).to_string())

    means = summary["dab_mean"].tolist()
    monotonic = all(a < b for a, b in zip(means, means[1:]))
    print(
        f"\nMonotonicity check (dab_mean must increase 0 -> 1+ -> 2+ -> 3+): "
        f"{'PASS' if monotonic else 'FAIL'}"
    )
    if not monotonic:
        print(
            "  Mean DAB density does not increase monotonically with the label.\n"
            "  Either the deconvolution is wrong, or the folder labels do not\n"
            "  mean patch-level staining intensity. Resolve before Phase 2."
        )

    _plot_distributions(frame, out_dir / "dab_by_class.png")
    print(f"\nArtifacts written to {out_dir.resolve()}")
    return 0 if monotonic else 1


def _plot_distributions(frame: pd.DataFrame, path: Path) -> None:
    order = [FOLDER_TO_SCORE[f] for f in CLASS_ORDER]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    data = [frame.loc[frame["patch_label"] == label, "dab_mean"].values for label in order]
    axes[0].boxplot(data, tick_labels=order)
    axes[0].set_xlabel("dataset class label")
    axes[0].set_ylabel("mean DAB optical density over tissue")
    axes[0].set_title("DAB density by class\n(must trend upward left to right)")
    axes[0].grid(alpha=0.3)

    bottom = np.zeros(len(order))
    for column, cls in (
        ("pct_negative", 1),
        ("pct_weak", 2),
        ("pct_moderate", 3),
        ("pct_strong", 4),
    ):
        values = np.array(
            [frame.loc[frame["patch_label"] == label, column].mean() for label in order]
        )
        axes[1].bar(
            order,
            values,
            bottom=bottom,
            label=CLASS_NAMES[cls],
            color=INTENSITY_COLORS[cls],
            edgecolor="white",
        )
        bottom += values
    axes[1].set_xlabel("dataset class label")
    axes[1].set_ylabel("mean % of tissue area")
    axes[1].set_title("Classical intensity composition by class")
    axes[1].legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    raise SystemExit(main())
