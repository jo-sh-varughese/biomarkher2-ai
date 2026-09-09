"""Sweep significance levels over the conformal predictor's held-out test half.

    python scripts/evaluate_conformal.py --run artifacts/phase2_unet

Reproduces the base paper's Section IV analysis (their Fig. 5-8): miscoverage
rate, ambiguity rate and singleton accuracy at a grid of significance levels
alpha, at both pixel level (their "image-level") and patch level (their
"case-level"). Requires scripts/calibrate_conformal.py to have been run
first, against the SAME run directory.

Runs both the plain (unweighted) predictor and the stain-shift-weighted one
against the same test patches, so the two curves sit in the same CSV and can
be compared directly. On HER2_IHC_40X (single-source; see
configs/preprocessing.yaml) the two should come out close to identical --
there is no real cross-institution stain shift in this dataset for weighting
to correct. That is not a bug in the comparison; it is the honest result of
running a cross-institution-shift correction on single-institution data. See
evaluation/conformal.py's module docstring.

Writes ``<run>/conformal_eval.csv`` (one row per alpha x weighting) and, with
matplotlib available, ``<run>/conformal_curves.png`` -- three panels
(miscoverage, ambiguity, accuracy vs. alpha), same layout as
scripts/plot_training.py's convention of one PNG per run.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.conformal import (
    ConformalCalibrator,
    aggregate_patch_status_from_mask,
    evaluate_patch_statuses,
    evaluate_prediction_mask,
    hinge_scores,
    prediction_mask,
)
from evaluation.stain_shift import median_bandwidth, patch_stain_descriptor
from models import prepare_pixel_array, select_architecture
from preprocessing.baseline import NUM_CLASSES
from preprocessing.sources import DirectoryPatchSource
from training.config import TrainingConfig
from training.pseudo_labels import PseudoLabelCache
from training.splits import stratified_subsample

ALPHA_GRID = [0.01, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]

CSV_FIELDS = [
    "alpha",
    "weighted",
    "pixel_miscoverage",
    "pixel_ambiguity",
    "pixel_accuracy",
    "patch_miscoverage",
    "patch_ambiguity",
    "patch_accuracy",
    "n_pixels",
    "n_patches",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="artifacts/phase2_unet")
    parser.add_argument("--config", default="configs/training.yaml")
    parser.add_argument(
        "--max-patches",
        type=int,
        default=None,
        help="Cap on test SOURCE PATCHES, for a smoke run, applied via "
        "training.splits.stratified_subsample -- a plain prefix slice of "
        "the (class-sorted) patch or tile list would smoke-test on one "
        "class only. Leave unset for a real evaluation.",
    )
    parser.add_argument("--no-plot", action="store_true")
    return parser.parse_args()


def load_calibrator(run_dir: Path) -> tuple[ConformalCalibrator, float]:
    data = np.load(run_dir / "conformal_calibration.npz")
    class_scores, class_descriptors, all_descriptors = {}, {}, []
    for c in range(1, NUM_CLASSES):
        key = f"scores_{c}"
        if key not in data:
            continue
        class_scores[c] = data[key]
        class_descriptors[c] = data[f"descriptors_{c}"]
        all_descriptors.append(data[f"descriptors_{c}"])
    if not class_scores:
        raise SystemExit(
            f"No calibration classes found in {run_dir / 'conformal_calibration.npz'}. "
            "Run scripts/calibrate_conformal.py first."
        )
    bandwidth = median_bandwidth(np.concatenate(all_descriptors, axis=0))
    return ConformalCalibrator.fit(class_scores, class_descriptors), bandwidth


def collect_test_tiles(
    run_dir: Path,
    cache: PseudoLabelCache,
    source: DirectoryPatchSource,
    max_patches: int | None,
    seed: int,
) -> list[str]:
    ids_path = run_dir / "conformal_calibration_ids.json"
    if not ids_path.is_file():
        raise SystemExit(f"No {ids_path}. Run scripts/calibrate_conformal.py first.")
    with open(ids_path, encoding="utf-8") as fh:
        ids = json.load(fh)
    test_patch_ids = [pid for pid in ids["test_patch_ids"] if cache.tile_ids(pid)]
    # Capped at the PATCH level via stratified_subsample, same reasoning as
    # scripts/calibrate_conformal.py: a prefix slice of a class-sorted tile
    # list smoke-tests on one class only.
    kept = stratified_subsample(source, test_patch_ids, cap=max_patches, seed=seed)
    return [t for pid in kept for t in cache.tile_ids(pid)]


def run_inference(model, normalize_batch, in_channels, cache, tile_ids, device):
    """One inference pass per tile, reused across every alpha in the grid."""
    per_tile = []
    model.eval()
    with torch.no_grad():
        for index, tile_id in enumerate(tile_ids, start=1):
            rgb, label = cache.read(tile_id)
            tissue = label != 0
            if not tissue.any():
                continue
            descriptor = patch_stain_descriptor(rgb, tissue_mask=tissue)
            # Not pre-divided by 255 -- see scripts/calibrate_conformal.py's
            # identical comment; the U-Net's 4th (DAB) channel is not a
            # 0..255 quantity and each architecture's own normalize_batch
            # scales its own channels correctly.
            array = prepare_pixel_array(rgb, in_channels)
            pixels = torch.from_numpy(np.ascontiguousarray(array))
            pixels = pixels.permute(2, 0, 1).float()[None].to(device)
            logits = model(normalize_batch(pixels))
            probs = logits.softmax(dim=1)[0].permute(1, 2, 0).cpu().numpy()
            per_tile.append(
                {
                    "scores": hinge_scores(probs[tissue]),
                    "true": label[tissue],
                    "descriptor": descriptor,
                }
            )
            if index % 50 == 0 or index == len(tile_ids):
                print(f"  [{index}/{len(tile_ids)}] {tile_id}", flush=True)
    return per_tile


def evaluate_alpha(calibrator, bandwidth, per_tile, alpha, weighted):
    """Metrics at one significance level, for one of the two predictors.

    Two things keep this tractable at real dataset scale -- a single
    512x512 tile can carry a few hundred thousand tissue pixels, and this
    runs once per (alpha, weighted) combination:

    1. The unweighted quantile does not depend on the test tile at all, so
       it is computed once per class here, not once per (class, tile).
    2. Prediction-set MEMBERSHIP is computed as a numpy boolean mask
       (:func:`evaluation.conformal.prediction_mask`), never as a Python
       ``set`` per pixel. Building millions of ``set`` objects in a Python
       loop -- one earlier version of this function did exactly that -- was
       the actual bottleneck the first time this script ran end to end: see
       PHASE4.md.
    """
    plain_quantiles = None
    if not weighted:
        plain_quantiles = {c: calib.quantile(alpha) for c, calib in calibrator.by_class.items()}

    pixel_masks, true_all, patch_statuses, patch_true = [], [], [], []
    for tile in per_tile:
        quantiles = (
            plain_quantiles
            if plain_quantiles is not None
            else {
                c: calib.quantile(alpha, test_descriptor=tile["descriptor"], bandwidth=bandwidth)
                for c, calib in calibrator.by_class.items()
            }
        )
        mask = prediction_mask(tile["scores"], quantiles)
        pixel_masks.append(mask)
        true_all.append(tile["true"])

        patch_statuses.append(aggregate_patch_status_from_mask(mask))
        values, counts = np.unique(tile["true"], return_counts=True)
        patch_true.append(int(values[np.argmax(counts)]))

    full_mask = np.concatenate(pixel_masks, axis=0)
    full_true = np.concatenate(true_all, axis=0)
    pixel_metrics = evaluate_prediction_mask(full_mask, full_true)
    patch_metrics = evaluate_patch_statuses(patch_statuses, patch_true)
    return pixel_metrics, patch_metrics


def main() -> int:
    args = parse_args()
    config = TrainingConfig.from_yaml(args.config)
    out_dir = Path(args.run)

    build_model, normalize_batch = select_architecture(config.model.architecture)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    checkpoint = torch.load(out_dir / "best.pt", map_location=device, weights_only=False)
    model = build_model(config.model, verbose=False).to(device)
    model.load_state_dict(checkpoint["model_state"])

    calibrator, bandwidth = load_calibrator(out_dir)
    cache = PseudoLabelCache(config.data.cache_root)
    source = DirectoryPatchSource(config.data.patch_root, splits=["train", "test"])
    test_tiles = collect_test_tiles(out_dir, cache, source, args.max_patches, config.seed)
    if not test_tiles:
        raise SystemExit("No test tiles found.")

    print(f"Evaluating {len(test_tiles)} held-out test tiles across "
          f"{len(ALPHA_GRID)} significance levels. device={device}")
    per_tile = run_inference(
        model, normalize_batch, config.model.in_channels, cache, test_tiles, device
    )

    rows = []
    for alpha in ALPHA_GRID:
        for weighted in (False, True):
            pixel_metrics, patch_metrics = evaluate_alpha(
                calibrator, bandwidth, per_tile, alpha, weighted
            )
            rows.append(
                {
                    "alpha": alpha,
                    "weighted": int(weighted),
                    "pixel_miscoverage": round(pixel_metrics.miscoverage_rate, 5),
                    "pixel_ambiguity": round(pixel_metrics.ambiguity_rate, 5),
                    "pixel_accuracy": round(pixel_metrics.accuracy, 5),
                    "patch_miscoverage": round(patch_metrics.miscoverage_rate, 5),
                    "patch_ambiguity": round(patch_metrics.ambiguity_rate, 5),
                    "patch_accuracy": round(patch_metrics.accuracy, 5),
                    "n_pixels": pixel_metrics.n,
                    "n_patches": patch_metrics.n,
                }
            )
            print(
                f"  alpha={alpha:<5} weighted={weighted}  "
                f"pixel miscoverage={pixel_metrics.miscoverage_rate:.3f} "
                f"ambiguity={pixel_metrics.ambiguity_rate:.3f} "
                f"accuracy={pixel_metrics.accuracy:.3f}"
            )

    csv_path = out_dir / "conformal_eval.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {csv_path}")

    if not args.no_plot:
        _plot(rows, out_dir / "conformal_curves.png")
    return 0


def _plot(rows: list[dict], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    alphas = sorted({r["alpha"] for r in rows})
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    panels = [
        ("pixel_miscoverage", "Miscoverage rate"),
        ("pixel_ambiguity", "Ambiguity rate"),
        ("pixel_accuracy", "Accuracy (singleton predictions)"),
    ]
    for ax, (field, title) in zip(axes, panels):
        for weighted, label, style in ((0, "unweighted", "-o"), (1, "stain-shift weighted", "--s")):
            ys = [r[field] for r in rows if r["weighted"] == weighted]
            ax.plot(alphas, ys, style, label=label, markersize=4)
        if field == "pixel_miscoverage":
            ax.plot(alphas, alphas, ":", color="grey", label="theoretical (y=alpha)")
        ax.set_xlabel("significance level (alpha)")
        ax.set_title(title)
        ax.legend(fontsize=8)
    fig.suptitle("Conformal prediction over the Phase 2 segmentation output")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    print(f"Wrote {path}")


if __name__ == "__main__":
    raise SystemExit(main())
