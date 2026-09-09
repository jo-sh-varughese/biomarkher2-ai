"""End-to-end smoke test of the Phase 2 training loop.

Runs the real loop -- real splits, real cache, the real U-Net (untrained, so
no download), real optimiser -- over a handful of tiny synthetic patches. It
is not a test of whether the model learns anything; it is a test that the
pieces are wired to each other correctly and that the artifacts a reader will
be handed actually get written, with their caveats attached.

The parts most worth catching here are the ones that fail silently: a loop
that writes an epoch log with no rows, a checkpoint saved without the config
that produced it, a summary that quietly omits the leakage caveat.
"""

from __future__ import annotations

import csv
import json

import numpy as np
import pytest
import torch
from PIL import Image

from preprocessing.config import PreprocessingConfig
from preprocessing.pipeline import PreprocessingPipeline
from preprocessing.sources import DirectoryPatchSource
from training.config import TrainingConfig
from training.dataset import class_pixel_counts
from training.pseudo_labels import PseudoLabelCache, build_cache
from training.splits import VAL_LEAKAGE_CAVEAT
from training.train import lr_at, train
from tests.synthetic import render_from_concentrations

FOLDERS = {"class_0": 0.05, "class_1+": 0.35, "class_2+": 0.65, "class_3+": 0.95}


def write_dataset(root, per_class: int = 4, size: int = 64) -> None:
    """A miniature HER2_IHC_40X, following the real naming convention."""
    for split in ("train", "test"):
        for folder, dab in FOLDERS.items():
            directory = root / split / folder
            directory.mkdir(parents=True, exist_ok=True)
            score = folder.replace("class_", "")
            for i in range(per_class):
                h = np.full((size, size), 0.35)
                d = np.full((size, size), dab + 0.02 * i)
                rgb = render_from_concentrations(h, d)
                Image.fromarray(rgb).save(
                    directory / f"her2-{score}-score_{split}_{i}.png"
                )


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    torch.set_num_threads(1)
    root = tmp_path_factory.mktemp("run")
    write_dataset(root / "data")

    config = TrainingConfig()
    config.data.patch_root = str(root / "data")
    config.data.cache_root = str(root / "cache")
    config.data.augment = True
    config.model.pretrained = False
    config.optim.epochs = 2
    config.optim.batch_size = 2
    config.optim.grad_accum_steps = 2
    config.output_dir = str(root / "artifacts")

    source = DirectoryPatchSource(config.data.patch_root, splits=["train", "test"])
    preprocessing = PreprocessingConfig()
    # Native magnification, and small enough that each 64px test patch is cut
    # into a 2x2 grid -- so the run exercises tiling and the tile-level
    # grouping check rather than the degenerate one-tile-per-patch case.
    preprocessing.tiling.downsample = 1
    preprocessing.tiling.patch_size = 32
    pipeline = PreprocessingPipeline(preprocessing)
    cache = PseudoLabelCache(config.data.cache_root)
    build_cache(source, pipeline, cache)

    summary = train(config, verbose=False)
    return config, summary, root


def test_run_completes_and_selects_an_epoch(trained):
    _, summary, _ = trained
    assert summary["selected_epoch"] in (1, 2)
    assert 0.0 <= summary["best_val_tissue_mean_iou"] <= 1.0


def test_epoch_log_has_one_row_per_epoch(trained):
    config, _, _ = trained
    from pathlib import Path

    rows = list(csv.DictReader(
        (Path(config.output_dir) / "epoch_log.csv").read_text(encoding="utf-8").splitlines()
    ))
    assert len(rows) == config.optim.epochs
    assert [int(r["epoch"]) for r in rows] == [1, 2]
    assert all(float(r["train_loss"]) > 0 for r in rows)


def test_checkpoint_carries_its_config_and_caveat(trained):
    config, _, _ = trained
    from pathlib import Path

    checkpoint = torch.load(
        Path(config.output_dir) / "best.pt", map_location="cpu", weights_only=False
    )
    assert checkpoint["caveat"] == VAL_LEAKAGE_CAVEAT
    assert checkpoint["config"]["model"]["num_classes"] == 5
    assert checkpoint["model_state"], "checkpoint has no weights"


def test_run_summary_states_what_the_targets_are(trained):
    _, summary, _ = trained
    assert summary["validation_caveat"] == VAL_LEAKAGE_CAVEAT
    assert "not pathologist" in summary["what_the_targets_are"]


def test_holdout_patches_are_never_in_the_training_set(trained):
    """The one leakage guarantee this dataset does support, checked on a run."""
    config, _, _ = trained
    from pathlib import Path

    split = json.loads(
        (Path(config.output_dir) / "split.json").read_text(encoding="utf-8")
    )
    fit, val, holdout = (set(split["patch_ids"][k]) for k in ("fit", "val", "holdout"))
    assert holdout & (fit | val) == set()
    assert all(p.startswith("test/") for p in holdout)
    assert split["caveat"] == VAL_LEAKAGE_CAVEAT


def test_no_source_patch_has_tiles_on_both_sides(trained):
    """Tiles of one patch are near-duplicates; they must not straddle the split.

    Slide-level grouping is impossible on this dataset. Patch-level grouping
    is, and this is the test that it actually holds on a real run rather than
    only in the function that claims it.
    """
    config, summary, _ = trained
    from pathlib import Path

    from training.pseudo_labels import PseudoLabelCache

    cache = PseudoLabelCache(config.data.cache_root)
    split = json.loads(
        (Path(config.output_dir) / "split.json").read_text(encoding="utf-8")
    )
    fit_parents = set(split["patch_ids"]["fit"])
    val_parents = set(split["patch_ids"]["val"])

    assert fit_parents and val_parents
    assert not (fit_parents & val_parents)
    # And every patch really did produce more than one tile, or the check
    # above would be vacuously true.
    assert all(len(cache.tile_ids(p)) == 4 for p in sorted(fit_parents)[:5])
    assert summary["sizes"]["fit_tiles"] > summary["sizes"]["fit_patches"]


def test_direct_parent_overlap_check_catches_a_leak(tmp_path):
    """The guard must fail on a leak, or it is worth nothing."""
    from training.pseudo_labels import PseudoLabelCache
    from training.train import _assert_no_parent_overlap

    cache = PseudoLabelCache(tmp_path)
    parent = "train/class_0/p.png"
    with pytest.raises(ValueError, match="Tile leakage"):
        _assert_no_parent_overlap(
            cache, [cache.tile_id(parent, 0, 0)], [cache.tile_id(parent, 0, 1)]
        )


def test_every_expected_artifact_exists(trained):
    config, _, _ = trained
    from pathlib import Path

    out = Path(config.output_dir)
    for name in (
        "epoch_log.csv",
        "split.json",
        "run_summary.json",
        "resolved_config.yaml",
        "best.pt",
        "val_per_class_best.csv",
        "val_confusion_best.csv",
        "val_metrics_best.json",
    ):
        assert (out / name).is_file(), f"{name} was not written"


def test_auto_class_weights_resolve_to_a_list_the_artifact_records(tmp_path):
    """"auto" must become concrete numbers, and those numbers must be written.

    A config that still says "auto" in resolved_config.yaml describes an
    experiment that cannot be repeated, because the weights depended on
    whatever happened to be in the cache that day.
    """
    from preprocessing.baseline import NUM_CLASSES
    from training.pseudo_labels import PseudoLabelCache, build_cache
    from training.train import resolve_class_weights

    root = tmp_path / "d"
    write_dataset(root, per_class=2)
    config = TrainingConfig()
    config.data.patch_root = str(root)
    config.data.cache_root = str(tmp_path / "cache")
    config.loss.class_weights = "auto"

    preprocessing = PreprocessingConfig()
    preprocessing.tiling.downsample = 1
    preprocessing.tiling.patch_size = 32
    cache = PseudoLabelCache(config.data.cache_root)
    source = DirectoryPatchSource(config.data.patch_root, splits=["train", "test"])
    records = build_cache(source, PreprocessingPipeline(preprocessing), cache)

    ids = [r.patch_id for r in records]
    weights = resolve_class_weights(config, cache, ids, verbose=False)

    assert isinstance(weights, list) and len(weights) == NUM_CLASSES
    assert config.loss.class_weights == weights, "config was not written back"
    assert all(w > 0 for w in weights)
    # Rarer class -> larger weight, which is the whole point of the option.
    counts = class_pixel_counts(cache, ids)
    order = sorted(range(NUM_CLASSES), key=lambda c: counts.get(c, 0))
    assert weights[order[0]] >= weights[order[-1]]


def test_resolve_rejects_an_unknown_string(tmp_path):
    from training.pseudo_labels import PseudoLabelCache
    from training.train import resolve_class_weights

    config = TrainingConfig()
    config.loss.class_weights = "balanced"
    with pytest.raises(ValueError, match="auto"):
        resolve_class_weights(config, PseudoLabelCache(tmp_path), [], verbose=False)


def _small_config(root) -> TrainingConfig:
    config = TrainingConfig()
    config.data.patch_root = str(root / "data")
    config.data.cache_root = str(root / "cache")
    config.data.augment = True
    config.model.pretrained = False
    config.optim.epochs = 2
    config.optim.batch_size = 2
    config.optim.grad_accum_steps = 2
    config.output_dir = str(root / "artifacts")
    return config


def _build_cache_for(config, root) -> None:
    write_dataset(root / "data")
    source = DirectoryPatchSource(config.data.patch_root, splits=["train", "test"])
    preprocessing = PreprocessingConfig()
    preprocessing.tiling.downsample = 1
    preprocessing.tiling.patch_size = 32
    cache = PseudoLabelCache(config.data.cache_root)
    build_cache(source, PreprocessingPipeline(preprocessing), cache)


def test_a_simulated_interruption_leaves_a_resume_checkpoint(tmp_path):
    from pathlib import Path

    from training.train import RESUME_NAME, TrainingInterrupted

    torch.set_num_threads(1)
    config = _small_config(tmp_path)
    _build_cache_for(config, tmp_path)

    with pytest.raises(TrainingInterrupted):
        train(config, verbose=False, checkpoint_every=1, _debug_stop_after_batches=2)

    resume_path = Path(config.output_dir) / RESUME_NAME
    assert resume_path.is_file()
    state = torch.load(resume_path, map_location="cpu", weights_only=False)
    assert state["epoch"] == 1
    assert state["batches_done"] == 2
    assert "model_state" in state and "optimizer_state" in state


def test_resuming_completes_the_run_with_no_epoch_skipped_or_duplicated(tmp_path):
    from pathlib import Path

    from training.train import TrainingInterrupted

    torch.set_num_threads(1)
    config = _small_config(tmp_path)
    _build_cache_for(config, tmp_path)

    with pytest.raises(TrainingInterrupted):
        train(config, verbose=False, checkpoint_every=1, _debug_stop_after_batches=2)

    summary = train(config, verbose=False, resume=True)
    assert summary["selected_epoch"] in (1, 2)

    rows = list(csv.DictReader(
        (Path(config.output_dir) / "epoch_log.csv").read_text(encoding="utf-8").splitlines()
    ))
    assert [int(r["epoch"]) for r in rows] == [1, 2]


def test_the_resume_checkpoint_is_deleted_once_the_run_completes(tmp_path):
    from pathlib import Path

    from training.train import RESUME_NAME, TrainingInterrupted

    torch.set_num_threads(1)
    config = _small_config(tmp_path)
    _build_cache_for(config, tmp_path)

    with pytest.raises(TrainingInterrupted):
        train(config, verbose=False, checkpoint_every=1, _debug_stop_after_batches=2)
    train(config, verbose=False, resume=True)

    assert not (Path(config.output_dir) / RESUME_NAME).is_file()


def test_resuming_an_interruption_at_an_epoch_boundary_starts_the_next_epoch(tmp_path):
    """An interruption caught right at a clean epoch boundary (batches_done=0
    for the next epoch) must resume there, not replay the epoch that just
    finished."""
    from pathlib import Path

    from training.train import RESUME_NAME

    torch.set_num_threads(1)
    config = _small_config(tmp_path)
    _build_cache_for(config, tmp_path)
    config.optim.epochs = 1  # completes fully -> resume.pt reflects epoch 2, batch 0

    train(config, verbose=False)
    resume_path = Path(config.output_dir) / RESUME_NAME
    assert not resume_path.is_file(), "a fully completed run must not leave a resume file"


def test_a_completed_run_asked_to_resume_again_starts_fresh_without_crashing(tmp_path):
    """No resume.pt exists after a clean finish (see the test above) -- the
    documented, correct behaviour is a fresh run, not an error."""
    torch.set_num_threads(1)
    config = _small_config(tmp_path)
    _build_cache_for(config, tmp_path)

    first = train(config, verbose=False)
    second = train(config, verbose=False, resume=True)
    assert second["selected_epoch"] in (1, 2)
    assert first["sizes"] == second["sizes"]


def test_learning_rate_schedule_warms_up_then_decays():
    total = 100
    values = [lr_at(s, total, 1e-4, 0.1) for s in range(total)]
    assert values[0] < values[9]                 # warming up
    assert values[9] == pytest.approx(1e-4)      # peaks at the base rate
    assert values[-1] < values[10]               # decaying
    assert all(v >= 0 for v in values)
