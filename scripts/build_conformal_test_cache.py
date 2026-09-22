"""Build pseudo-label tiles for the conformal TEST half of the reserved holdout.

    python scripts/build_conformal_test_cache.py --run artifacts/phase2_unet \\
        --cache data/cache/pseudo_labels_40x_holdout_test

Why this exists. scripts/build_pseudo_labels.py picks its holdout sample with
``stratified_subsample(..., seed)``, and the calibration/test split
(evaluation/calibration_split.py) is ``stratified_split(..., seed)`` over the
same population with the same seed, so both walk the same per-class
permutation. The builder keeps the first few patches of each class; the split's
calibration half is the first half of it. The cached holdout patches are
therefore almost exactly the calibration half: 285 of them are in it and 13 in
the test half, which is why evaluate_conformal.py only ever had 52 test tiles.

This builds the rest of the test half, from the ids scripts/calibrate_conformal.py
recorded, into a cache of its own. It refuses to write into the training cache:
training samples its patches from whatever tiles are on disk, so growing that
directory silently changes what the next "identical" run trains on (see
scripts/subset_pseudo_label_cache.py). Point scripts/evaluate_conformal.py at
the result with ``--cache``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from preprocessing.pipeline import PreprocessingPipeline
from preprocessing.sources import DirectoryPatchSource
from training.config import TrainingConfig
from training.pseudo_labels import PseudoLabelCache, build_cache
from training.splits import stratified_subsample


def build_test_cache(source, pipeline, cache, patch_ids, training_cache_root=None, progress=None):
    """Cache tiles for ``patch_ids`` and write the cache's manifest."""
    if training_cache_root is not None and (
        Path(cache.root).resolve() == Path(training_cache_root).resolve()
    ):
        raise SystemExit(
            f"{cache.root} is the training cache. Building into it would change which "
            "patches later training runs sample; use a cache directory of its own."
        )
    records = build_cache(source, pipeline, cache, patch_ids, progress=progress)
    if not records:
        raise SystemExit("No tiles were produced -- every patch fell below min_tissue_fraction.")
    cache.write_manifest(records)
    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="artifacts/phase2_unet")
    parser.add_argument("--cache", required=True, help="Destination cache directory.")
    parser.add_argument("--config", default="configs/training.yaml")
    parser.add_argument("--preprocessing-config", default="configs/preprocessing.yaml")
    parser.add_argument(
        "--max-patches",
        type=int,
        default=None,
        help="Cap on test SOURCE PATCHES, applied with stratified_subsample.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = TrainingConfig.from_yaml(args.config)
    pipeline = PreprocessingPipeline.from_yaml(args.preprocessing_config)

    ids_path = Path(args.run) / "conformal_calibration_ids.json"
    if not ids_path.is_file():
        raise SystemExit(f"No {ids_path}. Run scripts/calibrate_conformal.py first.")
    test_ids = json.loads(ids_path.read_text(encoding="utf-8"))["test_patch_ids"]

    source = DirectoryPatchSource(config.data.patch_root, splits=["train", "test"])
    kept = stratified_subsample(source, test_ids, cap=args.max_patches, seed=config.seed)
    cache = PseudoLabelCache(args.cache)
    print(f"Building tiles for {len(kept)} of {len(test_ids)} test-half patches into {cache.root}")

    def progress(index: int, total: int, patch_id: str) -> None:
        if index % 50 == 0 or index == total or index == 1:
            print(f"  [{index}/{total}] {patch_id}", flush=True)

    start = time.time()
    records = build_test_cache(
        source, pipeline, cache, kept, training_cache_root=config.data.cache_root, progress=progress
    )
    elapsed = time.time() - start
    print(f"Done in {elapsed:.0f}s: {len(records)} tiles. Manifest: {cache.manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
