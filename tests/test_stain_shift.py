"""Tests for the shared stain-descriptor and kernel-weight primitives."""

from __future__ import annotations

import numpy as np
import pytest

from evaluation.stain_shift import (
    descriptor_distance,
    gaussian_kernel_weights,
    median_bandwidth,
    patch_stain_descriptor,
    stain_descriptor,
)
from preprocessing.stains import HEMATOXYLIN, DAB, build_stain_matrix
from tests.synthetic import synthetic_patch


def test_stain_descriptor_drops_the_residual_row():
    matrix = build_stain_matrix()
    descriptor = stain_descriptor(matrix)
    assert descriptor.shape == (6,)
    np.testing.assert_allclose(descriptor[:3], matrix[0])
    np.testing.assert_allclose(descriptor[3:], matrix[1])


def test_stain_descriptor_rejects_wrong_shape():
    with pytest.raises(ValueError, match="3x3"):
        stain_descriptor(np.eye(2))


def test_descriptor_distance_is_zero_for_identical_descriptors():
    d = stain_descriptor(build_stain_matrix())
    assert descriptor_distance(d, d) == 0.0


def test_descriptor_distance_is_symmetric_and_positive_for_different_stains():
    a = stain_descriptor(build_stain_matrix(HEMATOXYLIN, DAB))
    # A visibly different "DAB" direction, still a valid unit stain vector.
    b = stain_descriptor(build_stain_matrix(HEMATOXYLIN, np.array([0.8, 0.3, 0.2])))
    assert descriptor_distance(a, b) > 0
    assert descriptor_distance(a, b) == pytest.approx(descriptor_distance(b, a))


def test_patch_stain_descriptor_returns_a_6_vector_from_pixels():
    rgb, mask = synthetic_patch(size=64, dab_level=0.6, hematoxylin_level=0.4)
    descriptor = patch_stain_descriptor(rgb, tissue_mask=mask)
    assert descriptor.shape == (6,)
    assert np.isfinite(descriptor).all()


def test_gaussian_kernel_weight_is_one_at_zero_distance():
    calib = np.array([[1.0, 0.0, 0.0, 0.0, 1.0, 0.0]])
    weights = gaussian_kernel_weights(calib, calib[0], bandwidth=0.5)
    assert weights[0] == pytest.approx(1.0)


def test_gaussian_kernel_weight_decays_with_distance():
    test = np.zeros(6)
    near = np.array([0.1, 0, 0, 0, 0, 0])
    far = np.array([5.0, 0, 0, 0, 0, 0])
    weights = gaussian_kernel_weights(np.stack([near, far]), test, bandwidth=1.0)
    assert weights[0] > weights[1]
    assert 0 < weights[1] < weights[0] <= 1.0


def test_gaussian_kernel_rejects_non_positive_bandwidth():
    with pytest.raises(ValueError, match="bandwidth"):
        gaussian_kernel_weights(np.zeros((3, 6)), np.zeros(6), bandwidth=0.0)


def test_median_bandwidth_is_scale_matched_to_the_data():
    tight = np.array([[0.0] * 6, [0.01] * 6, [-0.01] * 6])
    spread = np.array([[0.0] * 6, [10.0] * 6, [-10.0] * 6])
    assert median_bandwidth(tight) < median_bandwidth(spread)


def test_median_bandwidth_falls_back_to_one_for_a_single_point():
    assert median_bandwidth(np.zeros((1, 6))) == 1.0


def test_median_bandwidth_falls_back_to_one_when_every_row_is_identical():
    """The realistic large-n case: many pixels, one shared descriptor each."""
    assert median_bandwidth(np.tile([1.0, 0, 0, 0, 1.0, 0], (5000, 1))) == 1.0


def test_median_bandwidth_handles_millions_of_duplicated_rows_without_blowing_up():
    """The bug this function was rewritten to fix: naive pairwise distance
    over a per-pixel-expanded descriptor array tries to allocate a matrix
    that does not fit in memory. Two source tiles' worth of descriptors,
    broadcast to a million pixels each, must resolve from the 2 DISTINCT
    rows, not 2 million."""
    a = np.tile([1.0, 0, 0, 0, 1.0, 0], (1_000_000, 1))
    b = np.tile([-1.0, 0, 0, 0, -1.0, 0], (1_000_000, 1))
    descriptors = np.concatenate([a, b])
    bandwidth = median_bandwidth(descriptors)
    assert bandwidth == pytest.approx(np.linalg.norm([2.0, 0, 0, 0, 2.0, 0]))
