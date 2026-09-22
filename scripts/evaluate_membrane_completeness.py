"""Exploratory membrane-completeness analysis against a trained checkpoint.

    python scripts/evaluate_membrane_completeness.py --run artifacts/phase2_unet

Offline and evaluation-only, like evaluation/cap_mapping.py: nothing under
app/ imports it, and its output is a research measurement, not a HER2 result.
For each cached validation tile it (1) measures the morphology of the
DAB-stained connected components (evaluation/membrane_completeness.py) and
(2) runs the model and records its moderate (2+) errors against the
pseudo-label target, then reports Spearman correlations between the two.
See PHASE5_MEMBRANE_COMPLETENESS.md for what the numbers do and do not show.

Uses the VALIDATION split only. The reserved holdout is Phase 4's to spend,
once (training/splits.py) and is never read here. The validation split carries
its leakage caveat into summary.json.

Only validation patches that have tiles in the pseudo-label cache can be
evaluated. A cache built with a ``--limit`` covers a fraction of the split;
the summary reports how many were skipped for that reason rather than
pretending the whole split was scored.

Writes ``<output-dir>/patch_results.csv`` (one row per tile) and
``<output-dir>/summary.json``.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import torch
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.membrane_completeness import summarize_components
from models import select_architecture
from preprocessing.sources import DirectoryPatchSource
from preprocessing.stains import dab_channel
from training.config import TrainingConfig
from training.pseudo_labels import PseudoLabelCache
from training.splits import build_splits, stratified_subsample

MODERATE_CLASS = 3
DEFAULT_DAB_THRESHOLD = 0.25
DEFAULT_MIN_COMPONENT_AREA = 20


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        default="artifacts/phase2_unet",
        help="Run directory holding best.pt (default: the adopted baseline).",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Training config. Default: <run>/resolved_config.yaml, the run's "
        "own record. Not the config stored inside best.pt: older checkpoints "
        "carry keys the current schema rejects (the baseline's still names a "
        "SegFormer checkpoint).",
    )
    parser.add_argument(
        "--cache",
        default=None,
        help="Pseudo-label cache root. Default: the cache the run was trained "
        "on (its config's data.cache_root), so the targets match.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Default: <run>/membrane_completeness",
    )
    parser.add_argument(
        "--dab-threshold",
        type=float,
        default=DEFAULT_DAB_THRESHOLD,
        help="DAB optical density at or above which a pixel counts as stained "
        "(default equals dab_od_weak in configs/preprocessing.yaml).",
    )
    parser.add_argument(
        "--min-component-area",
        type=int,
        default=DEFAULT_MIN_COMPONENT_AREA,
    )
    parser.add_argument(
        "--max-patches",
        type=int,
        default=None,
        help="Cap on validation SOURCE PATCHES, for a smoke run, applied via "
        "training.splits.stratified_subsample -- a prefix slice of the "
        "(class-sorted) patch list would smoke-test on one class only. "
        "Leave unset for a real evaluation.",
    )
    return parser.parse_args()


def _safe_spearman(x: list[float], y: list[float]) -> dict:
    if len(x) < 3:
        return {
            "n": len(x),
            "rho": None,
            "p_value": None,
            "reason": "fewer than 3 observations",
        }
    if len(set(x)) < 2 or len(set(y)) < 2:
        return {
            "n": len(x),
            "rho": None,
            "p_value": None,
            "reason": "constant input",
        }

    result = spearmanr(x, y)

    rho = float(result.statistic)
    p_value = float(result.pvalue)

    return {
        "n": len(x),
        "rho": rho if np.isfinite(rho) else None,
        "p_value": p_value if np.isfinite(p_value) else None,
    }


def moderate_stats(target: np.ndarray, prediction: np.ndarray) -> dict:
    """Moderate (2+) agreement between a pseudo-label target and a prediction.

    ``moderate_iou`` is 0.0 when the class is absent from BOTH target and
    prediction (union == 0), because IoU is undefined there. That makes "no
    moderate anywhere in this tile" indistinguishable from "moderate present
    and entirely missed", so ``moderate_present`` is recorded alongside it and
    main() reports every correlation both over all tiles and over the
    moderate-present tiles only.
    """
    target = np.asarray(target)
    moderate_target = target == MODERATE_CLASS
    moderate_prediction = np.asarray(prediction) == MODERATE_CLASS

    intersection = int(np.logical_and(moderate_prediction, moderate_target).sum())
    union = int(np.logical_or(moderate_prediction, moderate_target).sum())
    false_positive = int(np.logical_and(moderate_prediction, ~moderate_target).sum())
    false_negative = int(np.logical_and(moderate_target, ~moderate_prediction).sum())
    size = moderate_target.size

    return {
        "moderate_target_pixels": int(moderate_target.sum()),
        "moderate_predicted_pixels": int(moderate_prediction.sum()),
        "moderate_false_positive_pixels": false_positive,
        "moderate_false_negative_pixels": false_negative,
        "moderate_present": int(union > 0),
        "moderate_iou": intersection / union if union > 0 else 0.0,
        "moderate_target_fraction": float(moderate_target.mean()),
        "moderate_prediction_fraction": float(moderate_prediction.mean()),
        "moderate_false_positive_fraction": false_positive / size,
        "moderate_false_negative_fraction": false_negative / size,
    }


def morphology_stats(features) -> dict:
    """Per-tile morphology summary; a tile with no component reads as all zeros."""
    if not features:
        return {
            "component_count": 0,
            "mean_completeness": 0.0,
            "median_completeness": 0.0,
            "mean_boundary_continuity": 0.0,
            "mean_ringness": 0.0,
        }
    completeness = [f.completeness for f in features]
    return {
        "component_count": len(features),
        "mean_completeness": float(np.mean(completeness)),
        "median_completeness": float(np.median(completeness)),
        "mean_boundary_continuity": float(np.mean([f.boundary_continuity for f in features])),
        "mean_ringness": float(np.mean([f.ringness for f in features])),
    }


def correlations(rows: list[dict]) -> dict:
    def col(name: str) -> list[float]:
        return [row[name] for row in rows]

    return {
        "completeness_vs_moderate_iou": _safe_spearman(
            col("mean_completeness"), col("moderate_iou")
        ),
        "completeness_vs_moderate_false_positive_fraction": _safe_spearman(
            col("mean_completeness"), col("moderate_false_positive_fraction")
        ),
        "completeness_vs_moderate_false_negative_fraction": _safe_spearman(
            col("mean_completeness"), col("moderate_false_negative_fraction")
        ),
        "ringness_vs_moderate_iou": _safe_spearman(
            col("mean_ringness"), col("moderate_iou")
        ),
        "continuity_vs_moderate_iou": _safe_spearman(
            col("mean_boundary_continuity"), col("moderate_iou")
        ),
    }


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run)
    output_dir = Path(args.output_dir) if args.output_dir else run_dir / "membrane_completeness"

    config_path = Path(args.config) if args.config else run_dir / "resolved_config.yaml"
    if not config_path.is_file():
        raise SystemExit(f"No config at {config_path}. Pass --config explicitly.")
    config = TrainingConfig.from_yaml(config_path)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    checkpoint_path = run_dir / "best.pt"
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)

    build_model, normalize_batch = select_architecture(config.model.architecture)
    model = build_model(config.model, verbose=False)
    model.load_state_dict(checkpoint["model_state"])
    model.to(device)
    model.eval()

    cache_root = Path(args.cache) if args.cache else Path(config.data.cache_root)
    cache = PseudoLabelCache(cache_root)
    source = DirectoryPatchSource(config.data.patch_root, splits=["train", "test"])
    split = build_splits(source, config.split)

    cached_val = [pid for pid in split.val if cache.tile_ids(pid)]
    cached_set = set(cached_val)
    without_tiles = [pid for pid in split.val if pid not in cached_set]
    if not cached_val:
        raise SystemExit(
            f"None of the {len(split.val)} validation patches has tiles in {cache_root}. "
            "Point --cache at a cache built for this checkpoint's data "
            "(scripts/build_pseudo_labels.py)."
        )
    evaluated = stratified_subsample(source, cached_val, cap=args.max_patches, seed=config.seed)

    print(
        f"Validation patches: {len(split.val)} in split, {len(cached_val)} with cached tiles "
        f"in {cache_root}, {len(evaluated)} evaluated. device={device}",
        flush=True,
    )

    rows: list[dict] = []
    with torch.no_grad():
        for source_index, parent_id in enumerate(evaluated, start=1):
            for tile_id in cache.tile_ids(parent_id):
                rgb, target = cache.read(tile_id)

                dab = dab_channel(rgb)
                features = summarize_components(
                    dab >= args.dab_threshold,
                    dab=dab,
                    min_area=args.min_component_area,
                )

                # Same construction as training/dataset.py: RGB in 0..1, then
                # DAB optical density as the fourth channel.
                pixels = torch.from_numpy(np.ascontiguousarray(rgb)).permute(2, 0, 1).float() / 255.0
                dab_tensor = torch.from_numpy(np.ascontiguousarray(dab.astype(np.float32))).unsqueeze(0)
                pixels = torch.cat([pixels, dab_tensor], dim=0).unsqueeze(0).to(device)

                logits = model(normalize_batch(pixels))
                prediction = logits.argmax(dim=1)[0].cpu().numpy()

                rows.append(
                    {
                        "patch_id": tile_id,
                        "parent_patch_id": parent_id,
                        "folder_class": int(source.label(parent_id) or 0),
                        **morphology_stats(features),
                        **moderate_stats(target, prediction),
                    }
                )

            if source_index % 25 == 0 or source_index == len(evaluated):
                print(
                    f"  [{source_index}/{len(evaluated)}] patches, {len(rows)} tiles",
                    flush=True,
                )

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "patch_results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    completeness = [row["mean_completeness"] for row in rows]
    moderate_present_rows = [row for row in rows if row["moderate_present"]]

    summary = {
        "checkpoint": str(checkpoint_path),
        "cache": str(cache_root),
        "split": "validation",
        "validation_source_patches_in_split": len(split.val),
        "validation_source_patches_with_cached_tiles": len(cached_val),
        "source_patches_evaluated": len(evaluated),
        "source_patches_without_cached_tiles": len(without_tiles),
        "without_cached_tiles_reason": (
            "not in the cache, or dropped at cache-build time for falling below "
            "min_tissue_fraction -- the cache does not record which"
        ),
        "without_cached_tiles_examples": without_tiles[:5],
        "cached_tiles_evaluated": len(rows),
        "tiles_with_moderate_present": len(moderate_present_rows),
        "device": device,
        "dab_threshold": args.dab_threshold,
        "min_component_area": args.min_component_area,
        "validation_caveat": split.caveat,
        "holdout_not_used": True,
        "mean_completeness": float(np.mean(completeness)),
        "median_completeness": float(np.median(completeness)),
        "correlations": correlations(rows),
        "correlations_moderate_present_only": correlations(moderate_present_rows),
    }

    json_path = output_dir / "summary.json"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print()
    print(json.dumps(summary, indent=2))
    print()
    print(f"Wrote: {csv_path}")
    print(f"Wrote: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
