"""Tissue / background separation.

The definition of "tissue" here is deliberately **stain-independent**: tissue
is anything absorbing meaningfully more light than bare slide glass. That
choice is forced by what this mask is used for. It becomes the denominator of
every area percentage downstream, so if the mask itself responded to staining
intensity, weakly-stained tissue would be dropped from the denominator and
the reported positive fractions would be inflated -- an error that is
invisible in the final numbers.

This is not hypothetical. The first implementation thresholded Otsu on the
HSV saturation channel, which is the textbook approach for low-magnification
whole-slide thumbnails. Measured on HER2_IHC_40X patches it failed badly:
median tissue saturation is 0.03-0.05 for the 0/1+/2+ classes while Otsu
chose a threshold of 0.12-0.15, so only haematoxylin-stained nuclei survived.
On 3+ patches Otsu chose 0.43 and kept only the DAB-stained membranes. Mean
detected tissue fraction rose from 0.17 to 0.42 with staining intensity,
which is the signature of a mask that measures stain rather than tissue.

Optical density (`method="od"`, the default) does not have that failure mode.
Saturation-based detection is kept available because it remains the better
choice for low-magnification thumbnails, where the field is mostly glass.
"""

from __future__ import annotations

import numpy as np
from skimage.color import rgb2hsv
from skimage.filters import threshold_otsu
from skimage.morphology import (
    closing,
    disk,
    opening,
    remove_small_holes,
    remove_small_objects,
)

from .config import TissueConfig
from .stains import rgb_to_od


def grey_optical_density(rgb: np.ndarray, background_intensity: float = 255.0):
    """Mean optical density across the RGB channels.

    Zero for bare glass, rising with anything that absorbs light, regardless
    of which stain does the absorbing.
    """
    return rgb_to_od(rgb, background_intensity).mean(axis=-1)


def detect_tissue(rgb: np.ndarray, config: TissueConfig | None = None) -> np.ndarray:
    """Return a boolean tissue mask for an RGB image. True marks tissue."""
    cfg = config or TissueConfig()
    array = np.asarray(rgb)
    if array.ndim != 3 or array.shape[-1] != 3:
        raise ValueError(f"Expected an HxWx3 RGB image, got shape {array.shape}")

    hsv = rgb2hsv(array.astype(np.float64) / 255.0)
    saturation = hsv[..., 1]
    value = hsv[..., 2]
    density = grey_optical_density(array, cfg.background_intensity)

    method = (cfg.method or "od").lower()
    if method == "od":
        core = density >= _od_threshold(density, cfg)
    elif method == "saturation":
        core = saturation >= _saturation_threshold(saturation, cfg)
    elif method == "combined":
        # Union: either absorbing enough, or chromatic enough. Catches
        # strongly coloured pixels that are somehow individually faint.
        core = (density >= _od_threshold(density, cfg)) | (
            saturation >= _saturation_threshold(saturation, cfg)
        )
    else:
        raise ValueError(
            f"Unknown tissue detection method {cfg.method!r}; "
            "expected one of 'od', 'saturation', 'combined'."
        )

    mask = (
        core
        & (value <= cfg.value_ceiling)   # not bare glass
        & (value >= cfg.value_floor)     # not a pen mark or dark artifact
        & (saturation >= cfg.achromatic_floor)  # not shadow/dust/out-of-focus grey
    )
    return _clean(mask, cfg)


def _od_threshold(density: np.ndarray, cfg: TissueConfig) -> float:
    """Optical-density cut point, optionally refined by Otsu.

    Otsu is capped by `otsu_od_ceiling`. Without that cap, a patch containing
    strong DAB staining lets Otsu drift up to split stained from unstained
    tissue -- reintroducing precisely the stain-dependence this method exists
    to avoid.
    """
    threshold = cfg.od_floor
    if cfg.use_otsu and density.size >= 16 and float(np.ptp(density)) > 1e-3:
        threshold = max(threshold, min(float(threshold_otsu(density)), cfg.otsu_od_ceiling))
    return threshold


def _saturation_threshold(saturation: np.ndarray, cfg: TissueConfig) -> float:
    threshold = cfg.saturation_floor
    if cfg.use_otsu and saturation.size >= 16 and float(np.ptp(saturation)) > 1e-3:
        threshold = max(float(threshold_otsu(saturation)), cfg.saturation_floor)
    return threshold


def _clean(mask: np.ndarray, cfg: TissueConfig) -> np.ndarray:
    """Morphological cleanup: close gaps, drop specks, fill pinholes."""
    if cfg.morph_radius > 0 and mask.any():
        footprint = disk(cfg.morph_radius)
        mask = closing(mask, footprint)
        mask = opening(mask, footprint)
    # scikit-image >= 0.26 takes `max_size`, which removes components smaller
    # than *or equal to* the value, whereas the config field means "remove
    # anything smaller than this". Subtracting one preserves that meaning.
    if cfg.min_object_area > 0 and mask.any():
        mask = remove_small_objects(mask, max_size=cfg.min_object_area - 1)
    if cfg.min_hole_area > 0 and mask.any():
        mask = remove_small_holes(mask, max_size=cfg.min_hole_area - 1)
    return mask.astype(bool)


def tissue_fraction(mask: np.ndarray) -> float:
    """Fraction of the mask that is tissue, in [0, 1]."""
    array = np.asarray(mask, dtype=bool)
    if array.size == 0:
        return 0.0
    return float(array.mean())
