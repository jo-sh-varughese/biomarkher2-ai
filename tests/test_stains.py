"""Tests for colour deconvolution and normalization.

The important tests here are the round-trip ones: because the synthetic
images are rendered from known stain concentrations, deconvolution must
recover those exact numbers. That checks the actual mathematics, not just
that arrays come out the right shape.
"""

from __future__ import annotations

import numpy as np
import pytest

from preprocessing.config import StainConfig
from preprocessing.stains import (
    DAB,
    DAB_CHANNEL,
    H_CHANNEL,
    HEMATOXYLIN,
    apply_normalization,
    build_stain_matrix,
    dab_channel,
    deconvolve,
    od_to_rgb,
    rgb_to_od,
)
from tests.synthetic import render_from_concentrations, synthetic_patch


def test_stain_matrix_rows_are_unit_vectors():
    matrix = build_stain_matrix()
    norms = np.linalg.norm(matrix, axis=1)
    np.testing.assert_allclose(norms, 1.0, atol=1e-12)


def test_stain_matrix_third_row_is_orthogonal_to_both_stains():
    matrix = build_stain_matrix()
    assert abs(float(matrix[2] @ matrix[0])) < 1e-12
    assert abs(float(matrix[2] @ matrix[1])) < 1e-12


def test_stain_matrix_is_invertible():
    assert abs(float(np.linalg.det(build_stain_matrix()))) > 1e-6


def test_collinear_stains_raise():
    with pytest.raises(ValueError, match="collinear"):
        build_stain_matrix(HEMATOXYLIN, HEMATOXYLIN * 2.0)


def test_od_round_trip():
    rgb = np.array([[[255, 255, 255], [128, 64, 32], [1, 1, 1]]], dtype=np.uint8)
    recovered = od_to_rgb(rgb_to_od(rgb))
    np.testing.assert_allclose(recovered, rgb, atol=1)


def test_white_pixel_has_zero_optical_density():
    white = np.full((4, 4, 3), 255, dtype=np.uint8)
    np.testing.assert_allclose(rgb_to_od(white), 0.0, atol=1e-12)


def test_deconvolution_recovers_known_concentrations():
    """The core correctness test for the quantitative claim."""
    h_level, d_level = 0.42, 0.73
    h = np.full((16, 16), h_level)
    d = np.full((16, 16), d_level)
    rgb = render_from_concentrations(h, d)

    stains = deconvolve(rgb)
    # uint8 quantisation of the rendered image limits achievable precision.
    np.testing.assert_allclose(stains[..., H_CHANNEL], h_level, atol=0.02)
    np.testing.assert_allclose(stains[..., DAB_CHANNEL], d_level, atol=0.02)
    np.testing.assert_allclose(stains[..., 2], 0.0, atol=0.02)


def test_dab_channel_isolates_dab_from_hematoxylin():
    """Varying haematoxylin alone must not move the DAB channel."""
    d = np.full((16, 16), 0.5)
    low = dab_channel(render_from_concentrations(np.full((16, 16), 0.1), d))
    high = dab_channel(render_from_concentrations(np.full((16, 16), 0.9), d))
    assert abs(float(low.mean()) - float(high.mean())) < 0.03


def test_dab_channel_is_monotonic_in_dab_concentration():
    h = np.full((16, 16), 0.3)
    means = [
        float(dab_channel(render_from_concentrations(h, np.full((16, 16), level))).mean())
        for level in (0.0, 0.25, 0.5, 0.75, 1.0)
    ]
    assert means == sorted(means)
    assert means[-1] > means[0] + 0.5


def test_concentrations_are_never_negative():
    rgb, _ = synthetic_patch(size=32)
    assert float(deconvolve(rgb).min()) >= 0.0


def test_deconvolve_rejects_non_rgb_input():
    with pytest.raises(ValueError, match="HxWx3"):
        deconvolve(np.zeros((8, 8), dtype=np.uint8))


def test_normalization_none_is_a_no_op():
    rgb, mask = synthetic_patch(size=32)
    out = apply_normalization(rgb, StainConfig(normalization="none"), tissue_mask=mask)
    np.testing.assert_array_equal(out, rgb)


@pytest.mark.parametrize("method", ["macenko", "reinhard"])
def test_normalization_preserves_shape_and_dtype(method):
    rgb, mask = synthetic_patch(size=48)
    out = apply_normalization(
        rgb, StainConfig(normalization=method), tissue_mask=mask
    )
    assert out.shape == rgb.shape
    assert out.dtype == np.uint8


def test_unknown_normalization_method_raises():
    rgb, _ = synthetic_patch(size=16)
    with pytest.raises(ValueError, match="Unknown normalization"):
        apply_normalization(rgb, StainConfig(normalization="nonsense"))


def test_macenko_falls_back_to_reference_when_tissue_is_absent():
    """A blank image cannot support stain estimation; it must not invent one."""
    from preprocessing.stains import estimate_macenko_stain_matrix

    blank = np.full((32, 32, 3), 255, dtype=np.uint8)
    np.testing.assert_allclose(
        estimate_macenko_stain_matrix(blank), build_stain_matrix(), atol=1e-12
    )


def test_reference_vectors_match_published_values():
    """Guards against an accidental edit to the published constants."""
    np.testing.assert_allclose(HEMATOXYLIN, [0.650, 0.704, 0.286])
    np.testing.assert_allclose(DAB, [0.268, 0.570, 0.776])
