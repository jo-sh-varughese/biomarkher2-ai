"""Build the Phase 2 pseudo-label cache, and render a preview of the targets.

    python scripts/build_pseudo_labels.py --limit 400 --preview 8

Writes ``data/cache/pseudo_labels/`` (image + label PNG per patch, a
manifest CSV, a summary JSON) and, with ``--preview``, a montage showing each
label map over the patch it came from.

Look at the montage before training on the cache. These targets are DAB
thresholds, not annotations -- if they are wrong, the model learns them wrong,
and no metric downstream will say so.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

from preprocessing.baseline import CLASS_NAMES, NUM_CLASSES
from preprocessing.pipeline import PreprocessingPipeline
from preprocessing.sources import DirectoryPatchSource
from training.config import TrainingConfig
from training.pseudo_labels import PseudoLabelCache, build_cache, summarize
from training.splits import build_splits, stratified_subsample

# Same ramp as the Phase 1 sanity check, so the two artifacts read alike:
# neutral background, then a light-to-dark orange/brown ramp that stays
# ordered under the common forms of colour blindness.
INTENSITY_COLORS = ["#f0f0f0", "#cfd8dc", "#ffd699", "#e08214", "#8c3d04"]
INTENSITY_CMAP = ListedColormap(INTENSITY_COLORS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/training.yaml")
    parser.add_argument("--preprocessing-config", default="configs/preprocessing.yaml")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cache only the first N patches of each side. Omit to do all of them.",
    )
    parser.add_argument(
        "--preview",
        type=int,
        default=8,
        help="How many patches to draw in the preview montage. 0 disables it.",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--out", default="artifacts/phase2")
    return parser.parse_args()


def progress(index: int, total: int, patch_id: str) -> None:
    if index % 50 == 0 or index == total or index == 1:
        print(f"  [{index}/{total}] {patch_id}", flush=True)


def render_preview(cache: PseudoLabelCache, patch_ids: list[str], path: Path) -> None:
    """Draw each label map beside, and over, the image it was derived from."""
    count = len(patch_ids)
    fig, axes = plt.subplots(count, 3, figsize=(9, 3 * count), squeeze=False)

    for row, patch_id in enumerate(patch_ids):
        rgb, label = cache.read(patch_id)

        axes[row][0].imshow(rgb)
        axes[row][0].set_title(patch_id.split("/")[-1], fontsize=7)

        axes[row][1].imshow(
            label, cmap=INTENSITY_CMAP, vmin=0, vmax=NUM_CLASSES - 1,
            interpolation="nearest",
        )
        axes[row][1].set_title("pseudo-label", fontsize=8)

        # The overlay is the panel that matters: it is the only one where a
        # label that has drifted off the membranes is obvious at a glance.
        axes[row][2].imshow(rgb)
        axes[row][2].imshow(
            np.ma.masked_where(label == 0, label),
            cmap=INTENSITY_CMAP, vmin=0, vmax=NUM_CLASSES - 1,
            alpha=0.45, interpolation="nearest",
        )
        axes[row][2].set_title("overlay", fontsize=8)

        for ax in axes[row]:
            ax.set_xticks([])
            ax.set_yticks([])

    handles = [
        Patch(facecolor=INTENSITY_COLORS[c], edgecolor="#555555", label=CLASS_NAMES[c])
        for c in range(NUM_CLASSES)
    ]
    fig.legend(handles=handles, loc="lower center", ncol=NUM_CLASSES, fontsize=8)
    fig.suptitle(
        "Phase 2 training targets -- DAB-threshold pseudo-labels, NOT annotations",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.97))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"Wrote {path}")


def main() -> int:
    args = parse_args()
    config = (
        TrainingConfig.from_yaml(args.config)
        if Path(args.config).is_file()
        else TrainingConfig()
    )
    pipeline = (
        PreprocessingPipeline.from_yaml(args.preprocessing_config)
        if Path(args.preprocessing_config).is_file()
        else PreprocessingPipeline()
    )

    source = DirectoryPatchSource(config.data.patch_root, splits=["train", "test"])
    print(f"{len(source)} patches under {config.data.patch_root}")

    split = build_splits(source, config.split)
    print(split.summary()["sizes"])
    if split.caveat:
        print(f"\nCAVEAT: {split.caveat}\n")

    # The cap is applied per side and per class. Patch ids sort by class
    # folder, so slicing the sorted list would cache class_0 patches only.
    wanted = [
        pid
        for side in (split.fit, split.val, split.holdout)
        for pid in stratified_subsample(source, side, args.limit, config.split.seed)
    ]

    cache = PseudoLabelCache(config.data.cache_root)
    print(f"Building {len(wanted)} targets into {cache.root} ...")
    start = time.time()
    records = build_cache(
        source, pipeline, cache, wanted, overwrite=args.overwrite, progress=progress
    )
    elapsed = time.time() - start
    cache.write_manifest(records)
    print(
        f"Done in {elapsed:.0f}s ({elapsed / max(1, len(records)):.2f}s/patch). "
        f"Manifest: {cache.manifest_path}"
    )

    summary = summarize(records)
    print("\nSanity check -- stained tissue area must rise with the folder label:")
    for name, stats in summary["per_folder_class"].items():
        print(
            f"  {name:<14} n={stats['patches']:<6} "
            f"stained={stats['mean_stained_fraction'] * 100:>6.2f}%  "
            f"tissue={stats['mean_tissue_fraction']:.3f}"
        )
    if summary["stained_fraction_is_monotonic"]:
        print("  -> monotonic. Deconvolution and thresholds are ordered correctly.")
    else:
        print(
            "  -> NOT MONOTONIC. Something upstream is wrong -- do not train on "
            "this cache until it is understood."
        )

    out_dir = Path(args.out)
    split.write(out_dir / "split.json")
    print(f"Wrote {out_dir / 'split.json'}")

    if args.preview:
        # One patch per folder class, repeated, so the preview always shows
        # the full intensity range rather than whatever sorts first.
        by_class: dict[int, list[str]] = {}
        for record in records:
            by_class.setdefault(record.folder_class, []).append(record.patch_id)
        chosen: list[str] = []
        rounds = 0
        while len(chosen) < args.preview and rounds < 10:
            for cls in sorted(by_class):
                if rounds < len(by_class[cls]) and len(chosen) < args.preview:
                    chosen.append(by_class[cls][rounds])
            rounds += 1
        render_preview(cache, chosen, out_dir / "pseudo_label_preview.png")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
