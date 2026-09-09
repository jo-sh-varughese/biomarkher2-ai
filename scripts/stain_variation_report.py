"""Report how much the estimated stain actually varies across provenance groups.

    python scripts/stain_variation_report.py

This is Objective 1 (adaptive stain-vector analysis) completed:
preprocessing/stains.py already estimates a Macenko stain matrix per patch,
but nothing ran that estimate over the whole dataset and asked how much it
varies. This script does that, over every one of HER2_IHC_40X's 8 provenance
groups (see preprocessing/sources.py -- NOT slides; this dataset has no
slide identifiers).

Writes ``artifacts/phase4/stain_variation.json`` (the full report;
see evaluation/stain_variation.py) and, with matplotlib available,
``artifacts/phase4/stain_variation.png`` (one point per patch, projected to
2D, coloured by group).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.stain_shift import patch_stain_descriptor
from evaluation.stain_variation import build_variation_report
from preprocessing.sources import DirectoryPatchSource
from training.splits import stratified_subsample


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patch-root", default="data/raw")
    parser.add_argument(
        "--per-group",
        type=int,
        default=150,
        help="Patches sampled per provenance group. Estimating a stain "
        "matrix touches every tissue pixel of a 1024x1024 image, so this "
        "trades runtime for precision -- unset by passing a large number "
        "for a full-dataset run.",
    )
    parser.add_argument("--seed", type=int, default=20260805)
    parser.add_argument("--out", default="artifacts/phase4")
    parser.add_argument("--no-plot", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = DirectoryPatchSource(args.patch_root, splits=["train", "test"])

    by_group: dict[str, list[str]] = {}
    for patch_id in source.list_ids():
        by_group.setdefault(source.group_key(patch_id), []).append(patch_id)

    descriptors_by_group: dict[str, np.ndarray] = {}
    for group, patch_ids in sorted(by_group.items()):
        sampled = stratified_subsample(source, patch_ids, cap=args.per_group, seed=args.seed)
        print(f"{group}: estimating stain over {len(sampled)}/{len(patch_ids)} patches")
        descriptors = []
        for index, patch_id in enumerate(sampled, start=1):
            rgb = source.read_patch(patch_id)
            descriptors.append(patch_stain_descriptor(rgb))
            if index % 50 == 0 or index == len(sampled):
                print(f"  [{index}/{len(sampled)}]", flush=True)
        descriptors_by_group[group] = np.stack(descriptors)

    report = build_variation_report(descriptors_by_group)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    report.write_json(out_dir / "stain_variation.json")
    print(f"\nWrote {out_dir / 'stain_variation.json'}")

    summary = report.summary()
    print(f"within-group spread (mean std norm): {summary['within_group_mean_std_norm']:.4f}")
    print(f"between-group mean distance:         {summary['between_group_mean_distance']:.4f}")
    print(f"variation exceeds noise:              {summary['variation_exceeds_noise']}")

    if not args.no_plot:
        _plot(descriptors_by_group, out_dir / "stain_variation.png")
    return 0


def _plot(descriptors_by_group: dict[str, np.ndarray], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    all_descriptors = np.concatenate(list(descriptors_by_group.values()), axis=0)
    mean = all_descriptors.mean(axis=0)
    centered = all_descriptors - mean
    # A 2D projection for a plot only -- the report's own numbers are
    # computed on the full 6-dimensional descriptor, never on this
    # projection. PCA via SVD, no sklearn dependency needed for two axes.
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    projection = centered @ vt[:2].T

    fig, ax = plt.subplots(figsize=(7, 6))
    start = 0
    for group, descriptors in sorted(descriptors_by_group.items()):
        n = descriptors.shape[0]
        points = projection[start : start + n]
        start += n
        ax.scatter(points[:, 0], points[:, 1], s=10, alpha=0.6, label=group)
    ax.set_xlabel("stain descriptor, principal component 1")
    ax.set_ylabel("stain descriptor, principal component 2")
    ax.set_title("Per-patch stain estimate, by provenance group\n(NOT slides -- see module docstring)")
    ax.legend(fontsize=7, markerscale=2)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    print(f"Wrote {path}")


if __name__ == "__main__":
    raise SystemExit(main())
