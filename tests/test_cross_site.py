"""Tests for site-level cross-institution stain normalization.

The images are rendered from known concentrations through two different
stain matrices (two "sites"), so the tests can check that the mapping
undoes a site shift, not just that it returns arrays of the right shape.
"""

from __future__ import annotations

import numpy as np
import pytest

from evaluation.cross_site import (
    SCALE_MODES,
    concentration_scale,
    fit_site_profile,
    normalize_to_site,
    reference_profile_identity,
    sample_tissue_pixels,
)
from preprocessing.config import StainConfig
from preprocessing.stains import (
    DAB,
    HEMATOXYLIN,
    build_stain_matrix,
    dab_channel,
    normalize_macenko,
    od_to_rgb,
)

# A second "site": haematoxylin bluer, DAB redder than the Ruifrok reference.
SITE_B_H = np.array([0.55, 0.75, 0.37])
SITE_B_DAB = np.array([0.35, 0.60, 0.72])


def _render(h, d, matrix):
    concentrations = np.stack([h, d, np.zeros_like(h)], axis=-1)
    return od_to_rgb(concentrations @ matrix)


def _random_field(rng, size, dab_mean):
    """Per-pixel H and DAB concentrations with a chosen average DAB level.

    Like real tissue, some pixels carry only one stain (nuclei with no
    membrane signal, membrane with little counterstain) -- Macenko finds the
    stain directions from exactly those extremes.
    """
    h = rng.uniform(0.1, 0.9, (size, size)) * (rng.random((size, size)) > 0.25)
    d = np.clip(rng.gamma(2.0, dab_mean / 2.0, (size, size)), 0, 2.0)
    d *= rng.random((size, size)) > 0.25
    return h, d


def _site_images(matrix, dab_scale, levels, seed=0, size=48):
    rng = np.random.default_rng(seed)
    images, dabs = [], []
    for level in levels:
        h, d = _random_field(rng, size, level)
        images.append(_render(h, d * dab_scale, matrix))
        dabs.append(d)
    return images, dabs


def _profile(images):
    rng = np.random.default_rng(1)
    samples = [
        sample_tissue_pixels(im, np.ones(im.shape[:2], bool), 2000, rng) for im in images
    ]
    return fit_site_profile(samples)


LEVELS = (0.02, 0.1, 0.3, 0.6, 0.9, 0.05, 0.4, 0.7)


def test_identical_profiles_are_close_to_identity():
    images, _ = _site_images(build_stain_matrix(), 1.0, LEVELS)
    profile = _profile(images)
    out = normalize_to_site(images[3], profile, profile, mode="per_stain")
    assert np.abs(out.astype(int) - images[3].astype(int)).max() <= 2


def test_fitted_site_vectors_recover_the_rendering_matrix():
    matrix_b = build_stain_matrix(SITE_B_H, SITE_B_DAB)
    images, _ = _site_images(matrix_b, 1.0, LEVELS)
    profile = _profile(images)
    for row in (0, 1):
        cosine = float(profile.stain_matrix[row] @ matrix_b[row])
        assert cosine > 0.98


def test_site_normalization_undoes_a_site_shift_better_than_doing_nothing():
    matrix_a = build_stain_matrix()
    matrix_b = build_stain_matrix(SITE_B_H, SITE_B_DAB)
    source_images, _ = _site_images(matrix_a, 1.0, LEVELS, seed=0)
    target_images, target_dab = _site_images(matrix_b, 1.6, LEVELS, seed=1)
    source = _profile(source_images)
    target = _profile(target_images)

    # What the same tissue would have looked like had it been stained at site A.
    errors_raw, errors_norm = [], []
    for image, true_dab in zip(target_images, target_dab):
        measured_raw = dab_channel(image)
        measured_norm = dab_channel(normalize_to_site(image, target, source, "per_stain"))
        errors_raw.append(np.abs(measured_raw - true_dab).mean())
        errors_norm.append(np.abs(measured_norm - true_dab).mean())
    assert np.mean(errors_norm) < 0.5 * np.mean(errors_raw)


def test_site_normalization_preserves_dab_ordering_but_per_image_macenko_does_not():
    """The reason this module exists: per-image normalization flattens DAB.

    A faint (score-0-like) image and a strong (3+-like) image from the same
    site must keep their DAB ratio after site-level normalization. Per-image
    Macenko rescales each image's own 99th percentile to the same value and
    so drags the faint one up toward the strong one.
    """
    matrix_b = build_stain_matrix(SITE_B_H, SITE_B_DAB)
    images, dabs = _site_images(matrix_b, 1.0, LEVELS)
    target = _profile(images)
    source = _profile(_site_images(build_stain_matrix(), 1.0, LEVELS, seed=3)[0])
    faint, strong = images[0], images[4]
    true_ratio = dabs[4].mean() / dabs[0].mean()

    site_ratio = (
        dab_channel(normalize_to_site(strong, target, source)).mean()
        / dab_channel(normalize_to_site(faint, target, source)).mean()
    )
    config = StainConfig()
    per_image_ratio = (
        dab_channel(normalize_macenko(strong, config)).mean()
        / dab_channel(normalize_macenko(faint, config)).mean()
    )
    assert abs(np.log(site_ratio / true_ratio)) < 0.2
    assert per_image_ratio < 0.5 * true_ratio


def test_concentration_scale_modes():
    target = reference_profile_identity()
    reference = reference_profile_identity()
    object.__setattr__(target, "concentration_p99", np.array([2.0, 4.0]))
    assert np.allclose(concentration_scale(target, reference, "per_stain"), [0.5, 0.25])
    assert np.allclose(concentration_scale(target, reference, "h_anchored"), [0.5, 0.5])
    assert np.allclose(concentration_scale(target, reference, "none"), [1.0, 1.0])
    assert set(SCALE_MODES) == {"per_stain", "h_anchored", "none", "quantile"}
    with pytest.raises(ValueError):
        concentration_scale(target, reference, "bogus")


def test_fit_requires_pixels():
    with pytest.raises(ValueError):
        fit_site_profile([])


def test_profile_serializes():
    images, _ = _site_images(build_stain_matrix(HEMATOXYLIN, DAB), 1.0, LEVELS)
    payload = _profile(images).to_dict()
    assert len(payload["stain_matrix"]) == 3
    assert len(payload["concentration_p99"]) == 2


def test_quantile_map_is_monotone_and_hits_the_reference_distribution():
    from evaluation.cross_site import QUANTILE_LEVELS, map_quantiles

    rng = np.random.default_rng(0)
    target_site = rng.gamma(2.0, 0.1, 50_000)  # compressed DAB range
    reference_site = rng.gamma(2.0, 0.3, 50_000) ** 1.2
    tq = np.percentile(target_site, QUANTILE_LEVELS)
    rq = np.percentile(reference_site, QUANTILE_LEVELS)
    mapped = map_quantiles(target_site, tq, rq)
    for level in (10, 50, 90, 99):
        assert np.percentile(mapped, level) == pytest.approx(np.percentile(reference_site, level), rel=0.05)
    order = np.argsort(target_site)
    assert np.all(np.diff(mapped[order]) >= -1e-9)
    assert map_quantiles(np.array([-0.1]), tq, rq)[0] == -0.1


def test_quantile_mode_undoes_a_site_shift():
    matrix_a = build_stain_matrix()
    matrix_b = build_stain_matrix(SITE_B_H, SITE_B_DAB)
    source = _profile(_site_images(matrix_a, 1.0, LEVELS, seed=0)[0])
    target_images, target_dab = _site_images(matrix_b, 0.5, LEVELS, seed=1)
    target = _profile(target_images)
    raw = np.mean([np.abs(dab_channel(im) - d).mean() for im, d in zip(target_images, target_dab)])
    norm = np.mean([
        np.abs(dab_channel(normalize_to_site(im, target, source, "quantile")) - d).mean()
        for im, d in zip(target_images, target_dab)
    ])
    assert norm < 0.6 * raw
