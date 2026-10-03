"""Cross-institution stain normalization: map one site's stain onto another's.

The project objective is "cross-institutional stain shift normalisation".
Everything else in this repo was built and measured on one source
(HER2_IHC_40X), so this module is the piece that lets a model trained there
be run on images from a different hospital, scanner and staining protocol.

WHY NOT THE EXISTING PER-IMAGE MACENKO
======================================
``preprocessing.stains.normalize_macenko`` is the textbook H&E recipe: it
estimates stain vectors from ONE image and rescales each stain so that
image's 99th-percentile concentration hits a fixed value. For HER2 IHC that
second step is actively harmful -- the amount of DAB *is* the signal. A
score-0 image (almost no DAB) gets its faint DAB stretched up to the same
99th percentile as a 3+ image, so per-image normalization erases exactly the
between-image intensity differences the score is read from. Per-image stain
vectors are also unstable on score-0 images, where there is too little DAB
for Macenko's angle extremes to find a real DAB direction.

WHAT THIS MODULE DOES INSTEAD: SITE-LEVEL PROFILES
==================================================
A :class:`SiteProfile` is estimated once per institution from a pooled pixel
sample across many of its images (no labels used): one Macenko stain matrix
for the whole site, and the site's pooled 99th-percentile concentration per
stain. :func:`normalize_to_site` then re-expresses a target-site image in the
source site's stain vectors and applies ONE fixed scale per stain for the
whole target site. Every image from that site gets the same transform, so
the relative DAB intensity between a 0 and a 3+ image is preserved -- only
the site's systematic colour/intensity offset is removed.

The fit uses unlabeled images only. Nothing here sees a HER2 score.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from preprocessing.stains import (
    build_stain_matrix,
    estimate_macenko_stain_matrix,
    od_to_rgb,
    rgb_to_od,
)

SCALE_MODES = ("per_stain", "h_anchored", "none", "quantile")
"""How concentration levels are matched between sites.

* ``per_stain``: haematoxylin and DAB each scaled by source_p99 / target_p99.
* ``h_anchored``: both stains scaled by the haematoxylin ratio only. The
  counterstain is roughly independent of HER2 status, so this does not depend
  on how many strongly positive cases happen to be in the fitting sample.
* ``none``: stain vectors are re-mapped, concentrations are left alone.
* ``quantile``: each stain's pooled concentration distribution at the target
  site is mapped onto the reference site's with one monotone curve
  (site-level histogram matching). Handles a scanner/compression response
  that compresses the top of the DAB range, which one linear scale cannot.
  Monotone and identical for every image, so between-image ordering holds.
"""

QUANTILE_LEVELS = np.concatenate([np.arange(0, 99, 1.0), np.arange(99, 100.01, 0.1)])


@dataclass(frozen=True)
class SiteProfile:
    stain_matrix: np.ndarray
    """3x3, rows = haematoxylin, DAB, residual (unit absorbance directions)."""

    concentration_p99: np.ndarray
    """(2,) pooled 99th-percentile concentration of haematoxylin and DAB."""

    lab_mean: np.ndarray
    lab_std: np.ndarray
    """Tissue-pixel Lab statistics, for the Reinhard comparison method."""

    n_images: int
    n_pixels: int

    concentration_quantiles: np.ndarray | None = None
    """(2, len(QUANTILE_LEVELS)) pooled H and DAB concentration quantiles."""

    def to_dict(self) -> dict:
        out = asdict(self)
        for key in ("stain_matrix", "concentration_p99", "lab_mean", "lab_std", "concentration_quantiles"):
            if out[key] is not None:
                out[key] = np.asarray(out[key]).round(6).tolist()
        return out


def sample_tissue_pixels(
    rgb: np.ndarray,
    tissue_mask: np.ndarray,
    max_pixels: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Up to ``max_pixels`` RGB tissue pixels from one image, as an (N, 3) array."""
    pixels = np.asarray(rgb, dtype=np.uint8)[np.asarray(tissue_mask, dtype=bool)]
    if pixels.shape[0] > max_pixels:
        pixels = pixels[rng.choice(pixels.shape[0], max_pixels, replace=False)]
    return pixels


def fit_site_profile(
    pixel_samples: list[np.ndarray],
    background_intensity: float = 255.0,
    macenko_alpha: float = 1.0,
    macenko_beta: float = 0.15,
) -> SiteProfile:
    """Estimate one stain profile from tissue pixels pooled across a site.

    ``pixel_samples`` is one (N_i, 3) uint8 array per image, e.g. from
    :func:`sample_tissue_pixels`. Pooling before estimating is the point:
    a site's stain vectors are a property of its reagents and scanner, and
    a pooled sample always contains enough DAB to find the DAB direction even
    when many individual images (score 0) do not.
    """
    if not pixel_samples:
        raise ValueError("Need at least one image's pixels to fit a site profile.")
    pooled = np.concatenate(pixel_samples, axis=0).astype(np.uint8)
    as_image = pooled[:, None, :]
    matrix = estimate_macenko_stain_matrix(
        as_image,
        alpha=macenko_alpha,
        beta=macenko_beta,
        background_intensity=background_intensity,
    )
    od = rgb_to_od(as_image, background_intensity).reshape(-1, 3)
    concentrations = np.clip(od @ np.linalg.pinv(matrix), 0.0, None)
    p99 = np.percentile(concentrations[:, :2], 99, axis=0)

    from skimage.color import rgb2lab

    lab = rgb2lab(as_image.astype(np.float64) / 255.0).reshape(-1, 3)
    return SiteProfile(
        stain_matrix=matrix,
        concentration_p99=p99,
        lab_mean=lab.mean(axis=0),
        lab_std=np.maximum(lab.std(axis=0), 1e-6),
        n_images=len(pixel_samples),
        n_pixels=int(pooled.shape[0]),
        concentration_quantiles=np.percentile(concentrations[:, :2], QUANTILE_LEVELS, axis=0).T,
    )


def concentration_scale(
    target: SiteProfile, reference: SiteProfile, mode: str = "per_stain"
) -> np.ndarray:
    """The fixed (H, DAB) multipliers applied to every image of the target site."""
    ratio = reference.concentration_p99 / np.maximum(target.concentration_p99, 1e-6)
    if mode == "per_stain":
        return ratio
    if mode == "h_anchored":
        return np.array([ratio[0], ratio[0]])
    if mode in ("none", "quantile"):
        return np.ones(2)
    raise ValueError(f"Unknown scale mode {mode!r}; expected one of {SCALE_MODES}.")


def normalize_to_site(
    rgb: np.ndarray,
    target: SiteProfile,
    reference: SiteProfile,
    mode: str = "per_stain",
    background_intensity: float = 255.0,
) -> np.ndarray:
    """Re-render a target-site image as if stained and scanned at the reference site.

    Decompose with the TARGET site's stain matrix, apply the site-level
    concentration scale, recompose with the REFERENCE site's stain matrix.
    The residual channel is carried across unscaled so nothing the two
    stains do not explain is silently thrown away.
    """
    scale = concentration_scale(target, reference, mode)
    od = rgb_to_od(rgb, background_intensity)
    height, width, _ = od.shape
    concentrations = od.reshape(-1, 3) @ np.linalg.pinv(target.stain_matrix)
    if mode == "quantile":
        for channel in (0, 1):
            concentrations[:, channel] = map_quantiles(
                concentrations[:, channel],
                target.concentration_quantiles[channel],
                reference.concentration_quantiles[channel],
            )
    concentrations[:, 0] *= scale[0]
    concentrations[:, 1] *= scale[1]
    recombined = (concentrations @ reference.stain_matrix).reshape(height, width, 3)
    return od_to_rgb(recombined, background_intensity)


def map_quantiles(values: np.ndarray, source_q: np.ndarray, target_q: np.ndarray) -> np.ndarray:
    """Monotone piecewise-linear map taking ``source_q`` onto ``target_q``.

    Values above the top source quantile are scaled by the ratio of the top
    quantiles rather than clamped, so the very strongest staining is not
    flattened. Negative values (deconvolution noise) pass through unchanged.
    """
    source_q = np.maximum.accumulate(np.asarray(source_q, dtype=np.float64))
    target_q = np.maximum.accumulate(np.asarray(target_q, dtype=np.float64))
    # np.interp needs strictly increasing x; nudge ties apart.
    source_q = source_q + np.arange(source_q.size) * 1e-9
    out = np.interp(values, source_q, target_q)
    top = values > source_q[-1]
    out[top] = values[top] * (target_q[-1] / max(source_q[-1], 1e-6))
    negative = values < 0
    out[negative] = values[negative]
    return out


def normalize_reinhard_to_site(
    rgb: np.ndarray,
    reference: SiteProfile,
    tissue_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Per-image Reinhard Lab matching onto the reference site's tissue statistics.

    Included as the standard comparison method. Like per-image Macenko it
    matches each image's own statistics, so it shares the same weakness on
    IHC: it pulls every image's DAB-driven colour toward one mean.
    """
    from preprocessing.stains import normalize_reinhard

    return normalize_reinhard(
        rgb,
        tissue_mask=tissue_mask,
        target_mean=tuple(np.asarray(reference.lab_mean, dtype=float)),
        target_std=tuple(np.asarray(reference.lab_std, dtype=float)),
    )


def reference_profile_identity() -> SiteProfile:
    """A profile at the Ruifrok reference vectors -- used only in tests."""
    return SiteProfile(
        stain_matrix=build_stain_matrix(),
        concentration_p99=np.array([1.0, 1.0]),
        lab_mean=np.zeros(3),
        lab_std=np.ones(3),
        n_images=0,
        n_pixels=0,
    )
