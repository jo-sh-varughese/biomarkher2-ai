"""Tests for tissue / background separation."""

from __future__ import annotations

import numpy as np
import pytest

from preprocessing.config import TissueConfig
from preprocessing.tissue import detect_tissue, tissue_fraction
from tests.synthetic import synthetic_patch


def test_detects_stained_region_and_rejects_glass():
    rgb, expected = synthetic_patch(size=64)
    # Cleanup morphology nibbles at the border, so compare on agreement rate
    # rather than demanding an exact match.
    mask = detect_tissue(rgb, TissueConfig(min_object_area=16, min_hole_area=16))
    agreement = float((mask == expected).mean())
    assert agreement > 0.95
    assert mask[32, 32]      # centre of the tissue box
    assert not mask[2, 2]    # corner is bare glass


def test_pure_white_image_has_no_tissue():
    white = np.full((64, 64, 3), 255, dtype=np.uint8)
    assert not detect_tissue(white).any()


def test_pure_black_image_is_rejected_as_artifact():
    """Black regions are pen marks or scanning artifacts, not tissue."""
    black = np.zeros((64, 64, 3), dtype=np.uint8)
    assert not detect_tissue(black).any()


def test_grey_image_has_no_tissue():
    """Grey is achromatic: no stain, so no tissue, whatever Otsu says."""
    grey = np.full((64, 64, 3), 180, dtype=np.uint8)
    assert not detect_tissue(grey).any()


def test_small_specks_are_removed():
    rgb = np.full((64, 64, 3), 255, dtype=np.uint8)
    rgb[10:13, 10:13] = (120, 60, 30)  # a 3x3 speck, area 9
    mask = detect_tissue(rgb, TissueConfig(min_object_area=100))
    assert not mask.any()


def test_speck_survives_when_threshold_is_lowered():
    """Complement of the previous test: removal is the config's doing."""
    rgb = np.full((64, 64, 3), 255, dtype=np.uint8)
    rgb[10:20, 10:20] = (120, 60, 30)
    mask = detect_tissue(
        rgb, TissueConfig(min_object_area=4, min_hole_area=4, morph_radius=1)
    )
    assert mask.any()


def test_holes_are_filled():
    rgb, _ = synthetic_patch(size=64)
    rgb[30:33, 30:33] = 255  # punch a small hole in the tissue
    mask = detect_tissue(rgb, TissueConfig(min_hole_area=64, min_object_area=16))
    assert mask[31, 31]


def test_mask_is_boolean():
    rgb, _ = synthetic_patch(size=32)
    assert detect_tissue(rgb).dtype == bool


def test_rejects_non_rgb_input():
    with pytest.raises(ValueError, match="HxWx3"):
        detect_tissue(np.zeros((8, 8), dtype=np.uint8))


def test_detected_area_is_independent_of_staining_intensity():
    """The regression test for the defect this module was rewritten to fix.

    The tissue box is identical in every image; only the DAB concentration
    varies. A detector that responds to staining reports a growing area,
    which would inflate every downstream area percentage by shrinking their
    denominator on weakly-stained tissue.
    """
    config = TissueConfig(min_object_area=16, min_hole_area=16)
    fractions = []
    for dab_level in (0.05, 0.2, 0.5, 0.9, 1.4):
        rgb, _ = synthetic_patch(size=64, dab_level=dab_level, hematoxylin_level=0.05)
        fractions.append(tissue_fraction(detect_tissue(rgb, config)))
    assert max(fractions) - min(fractions) < 0.02, (
        f"Detected tissue area varies with staining: {fractions}"
    )


def test_faintly_stained_tissue_is_still_tissue():
    """Pale, barely-stained tissue must survive; it is the negative class."""
    rgb, expected = synthetic_patch(
        size=64, dab_level=0.03, hematoxylin_level=0.06
    )
    mask = detect_tissue(rgb, TissueConfig(min_object_area=16, min_hole_area=16))
    assert float((mask == expected).mean()) > 0.95


def test_saturation_method_is_still_available():
    rgb, _ = synthetic_patch(size=64)
    mask = detect_tissue(
        rgb, TissueConfig(method="saturation", min_object_area=16, min_hole_area=16)
    )
    assert mask.any()


def test_unknown_method_raises():
    rgb, _ = synthetic_patch(size=32)
    with pytest.raises(ValueError, match="Unknown tissue detection method"):
        detect_tissue(rgb, TissueConfig(method="nonsense"))


def test_otsu_threshold_is_capped():
    """An uncapped Otsu on a strongly-stained patch re-splits the tissue."""
    rgb, expected = synthetic_patch(size=64, dab_level=1.5, hematoxylin_level=0.05)
    config = TissueConfig(
        use_otsu=True, otsu_od_ceiling=0.15, min_object_area=16, min_hole_area=16
    )
    assert float((detect_tissue(rgb, config) == expected).mean()) > 0.95


def test_tissue_fraction_bounds():
    assert tissue_fraction(np.ones((4, 4), dtype=bool)) == 1.0
    assert tissue_fraction(np.zeros((4, 4), dtype=bool)) == 0.0
    assert tissue_fraction(np.array([[True, False]])) == 0.5


def test_tissue_fraction_of_empty_array_is_zero():
    assert tissue_fraction(np.zeros((0, 0), dtype=bool)) == 0.0
