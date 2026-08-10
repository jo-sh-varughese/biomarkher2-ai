"""Tests for the composed pipeline, config loading, and the classical baseline."""

from __future__ import annotations

import numpy as np
import pytest

from preprocessing.baseline import (
    CLASS_BACKGROUND,
    CLASS_MODERATE,
    CLASS_NEGATIVE,
    CLASS_STRONG,
    CLASS_WEAK,
    TISSUE_CLASSES,
    area_distribution,
    dab_statistics,
    intensity_map,
)
from preprocessing.config import (
    PreprocessingConfig,
    StainConfig,
    TilingConfig,
    TissueConfig,
)
from preprocessing.pipeline import PreprocessingPipeline
from preprocessing.sources import DirectoryPatchSource, _parse_filename
from tests.synthetic import graded_patch, render_from_concentrations, synthetic_patch


# ---------------------------------------------------------------- config


def test_config_round_trips_through_yaml(tmp_path):
    config = PreprocessingConfig(
        tissue=TissueConfig(min_object_area=99),
        stain=StainConfig(normalization="macenko", dab_od_weak=0.3),
        tiling=TilingConfig(patch_size=256, overlap=32),
    )
    path = tmp_path / "cfg.yaml"
    config.to_yaml(path)
    loaded = PreprocessingConfig.from_yaml(path)
    assert loaded.tissue.min_object_area == 99
    assert loaded.stain.normalization == "macenko"
    assert loaded.stain.dab_od_weak == 0.3
    assert loaded.tiling.patch_size == 256
    assert loaded.tiling.overlap == 32


def test_unknown_config_key_raises_rather_than_being_ignored():
    """A silently-ignored YAML typo makes a run irreproducible."""
    with pytest.raises(ValueError, match="Unknown key"):
        PreprocessingConfig.from_dict({"tissue": {"min_objct_area": 10}})


def test_unknown_config_section_raises():
    with pytest.raises(ValueError, match="Unknown config section"):
        PreprocessingConfig.from_dict({"tisue": {}})


def test_empty_config_yields_defaults():
    assert PreprocessingConfig.from_dict({}).tiling.patch_size == 512


# -------------------------------------------------------------- baseline


def test_intensity_map_assigns_expected_classes_per_band():
    """Four bands of known DAB density must land in the four intensity classes."""
    rgb = graded_patch(size=64)
    mask = np.ones((64, 64), dtype=bool)
    classes = intensity_map(rgb, mask)
    # Sample the middle of each band, away from boundaries.
    assert classes[32, 8] == CLASS_NEGATIVE    # 0.00
    assert classes[32, 24] == CLASS_WEAK       # 0.35
    assert classes[32, 40] == CLASS_MODERATE   # 0.65
    assert classes[32, 56] == CLASS_STRONG     # 0.95


def test_non_tissue_is_always_background_even_when_stained():
    """Guards the rule that glass cannot be scored, whatever its DAB value."""
    rgb = render_from_concentrations(np.full((16, 16), 0.3), np.full((16, 16), 0.9))
    mask = np.zeros((16, 16), dtype=bool)
    assert (intensity_map(rgb, mask) == CLASS_BACKGROUND).all()


def test_thresholds_must_be_increasing():
    rgb, mask = synthetic_patch(size=16)
    bad = StainConfig(dab_od_weak=0.9, dab_od_moderate=0.5, dab_od_strong=0.8)
    with pytest.raises(ValueError, match="strictly increasing"):
        intensity_map(rgb, mask, bad)


def test_intensity_map_rejects_mismatched_mask():
    rgb, _ = synthetic_patch(size=32)
    with pytest.raises(ValueError, match="does not match"):
        intensity_map(rgb, np.ones((8, 8), dtype=bool))


def test_area_distribution_sums_to_one_over_tissue():
    classes = np.array([[1, 2], [3, 4]], dtype=np.uint8)
    dist = area_distribution(classes)
    assert pytest.approx(sum(dist.fractions.values())) == 1.0
    assert dist.tissue_pixels == 4
    assert all(pytest.approx(dist.percentages[c]) == 25.0 for c in TISSUE_CLASSES)


def test_area_distribution_excludes_background_from_the_denominator():
    """Framing decides how much glass is in shot; it must not move the numbers."""
    classes = np.array([[0, 0, 0], [0, 2, 4]], dtype=np.uint8)
    dist = area_distribution(classes)
    assert dist.tissue_pixels == 2
    assert pytest.approx(dist.percentages[CLASS_WEAK]) == 50.0
    assert pytest.approx(dist.percentages[CLASS_STRONG]) == 50.0


def test_area_distribution_of_all_background_is_safe():
    dist = area_distribution(np.zeros((4, 4), dtype=np.uint8))
    assert dist.tissue_pixels == 0
    assert dist.tissue_fraction == 0.0
    assert sum(dist.fractions.values()) == 0.0


def test_dab_statistics_increase_with_staining():
    h = np.full((16, 16), 0.3)
    mask = np.ones((16, 16), dtype=bool)
    low = dab_statistics(render_from_concentrations(h, np.full((16, 16), 0.1)), mask)
    high = dab_statistics(render_from_concentrations(h, np.full((16, 16), 0.9)), mask)
    assert high["dab_mean"] > low["dab_mean"]


def test_dab_statistics_on_empty_mask_are_zero():
    rgb, _ = synthetic_patch(size=16)
    stats = dab_statistics(rgb, np.zeros((16, 16), dtype=bool))
    assert stats["dab_mean"] == 0.0


# -------------------------------------------------------------- pipeline


def test_pipeline_produces_consistent_shapes():
    rgb, _ = synthetic_patch(size=64)
    result = PreprocessingPipeline().run(rgb, patch_id="p1")
    assert result.patch_id == "p1"
    assert result.tissue_mask.shape == (64, 64)
    assert result.dab.shape == (64, 64)
    assert result.hematoxylin.shape == (64, 64)
    assert result.intensity.shape == (64, 64)
    assert 0.0 < result.tissue_fraction < 1.0


def test_pipeline_intensity_classes_are_in_range():
    rgb, _ = synthetic_patch(size=64)
    result = PreprocessingPipeline().run(rgb)
    assert set(np.unique(result.intensity)).issubset({0, 1, 2, 3, 4})


def test_pipeline_emits_tiles_only_when_asked():
    rgb, _ = synthetic_patch(size=64)
    config = PreprocessingConfig(
        tiling=TilingConfig(
            patch_size=16, overlap=0, downsample=1, min_tissue_fraction=0.0
        )
    )
    pipeline = PreprocessingPipeline(config)
    assert pipeline.run(rgb).tiles == []
    assert len(pipeline.run(rgb, with_tiles=True).tiles) == 16


def test_pipeline_rejects_non_rgb_input():
    with pytest.raises(ValueError, match="HxWx3"):
        PreprocessingPipeline().run(np.zeros((8, 8), dtype=np.uint8))


def test_pipeline_is_deterministic():
    rgb, _ = synthetic_patch(size=48)
    pipeline = PreprocessingPipeline()
    first, second = pipeline.run(rgb), pipeline.run(rgb)
    np.testing.assert_array_equal(first.intensity, second.intensity)
    np.testing.assert_array_equal(first.dab, second.dab)


# --------------------------------------------------------------- sources


@pytest.mark.parametrize(
    "name,expected",
    [
        ("her2-0-score_test_09.png", ("0", "test")),
        ("her2-1+-score_train_1302.png", ("1+", "train")),
        ("her2-2+-score_test_178.png", ("2+", "test")),
        ("her2-3+-score_train_16.png", ("3+", "train")),
        ("her2-0-score_test_01.jpg", ("0", "test")),
    ],
)
def test_filename_parsing(name, expected):
    assert _parse_filename(name) == expected


def test_unparseable_filename_returns_none_rather_than_guessing():
    assert _parse_filename("random_image.png") == (None, None)


def _write_patch(path, dab_level=0.5):
    from PIL import Image

    rgb = render_from_concentrations(
        np.full((16, 16), 0.3), np.full((16, 16), dab_level)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb).save(path)


def test_directory_source_reads_labels_and_grouping(tmp_path):
    _write_patch(tmp_path / "train" / "class_0" / "her2-0-score_train_1.png")
    _write_patch(tmp_path / "train" / "class_3+" / "her2-1+-score_train_2.png")

    source = DirectoryPatchSource(tmp_path, splits=["train"])
    ids = source.list_ids()
    assert len(ids) == 2

    negative = [i for i in ids if "class_0" in i][0]
    strong = [i for i in ids if "class_3+" in i][0]

    assert source.label(negative) == 1  # folder class_0 -> negative
    assert source.label(strong) == 4    # folder class_3+ -> strong
    assert source.read_patch(negative).shape == (16, 16, 3)

    # The filename records the SOURCE SLIDE score, which legitimately differs
    # from the patch-level label. Both must survive.
    assert source.record(strong).slide_score == "1+"
    assert source.record(strong).patch_score == "3+"
    assert source.group_key(strong) == "her2-1+-score_train"


def test_directory_source_rejects_empty_root(tmp_path):
    (tmp_path / "train").mkdir()
    with pytest.raises(ValueError, match="No patches found"):
        DirectoryPatchSource(tmp_path, splits=["train"])


def test_directory_source_rejects_missing_root(tmp_path):
    with pytest.raises(FileNotFoundError):
        DirectoryPatchSource(tmp_path / "nope")


def test_unknown_patch_id_raises(tmp_path):
    _write_patch(tmp_path / "class_0" / "her2-0-score_train_1.png")
    source = DirectoryPatchSource(tmp_path)
    with pytest.raises(KeyError, match="Unknown patch id"):
        source.read_patch("not-a-real-id")
