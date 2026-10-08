"""Per-slide DAB calibration against on-slide control tissue.

HER2 slides are usually stained alongside a control of known score (often a
3+ control section on the same slide or in the same run). The control went
through the same antibody, chromogen timing and scanner as the patient
tissue, so how dark ITS DAB came out measures that run's staining strength
directly. Ohnishi et al. (Applied Microscopy, 2023) used the same principle
with IHC calibrator slides and cut automated-vs-pathologist discordance on 30
HER2 slides from 14/30 to 0/30.

Method
------
1. ``control_signature`` measures a control region's DAB optical-density
   distribution (percentiles over stained tissue pixels).
2. ``calibration_gain`` compares it with the training site's reference
   control: gain = reference percentile / slide percentile.
3. ``apply_dab_gain`` rescales that slide's DAB concentration by the gain
   (haematoxylin untouched), so a control that came out pale is brought back
   to the darkness the model was trained on -- and the patient tissue on the
   same slide with it.

Unlike site-level normalization (one correction per hospital), this corrects
every slide separately, so run-to-run variation inside one lab is removed too.
"""

from __future__ import annotations

import numpy as np

from preprocessing.stains import build_stain_matrix, deconvolve, od_to_rgb
from preprocessing.tissue import detect_tissue

PERCENTILES = (50, 75, 90, 95, 99)


def control_signature(rgb: np.ndarray, prep, region: tuple[int, int, int, int] | None = None) -> dict:
    """DAB OD percentiles over the stained tissue of a control (optionally a box: top, left, bottom, right)."""
    if region is not None:
        top, left, bottom, right = region
        rgb = rgb[top:bottom, left:right]
    tissue = detect_tissue(rgb, prep.tissue)
    dab = deconvolve(rgb)[..., 1][tissue]
    return signature_from_dab(dab[dab >= prep.stain.thresholds()[0]])


def signature_from_dab(stained: np.ndarray) -> dict:
    """DAB OD percentiles of already-selected DAB-stained pixels (one or several control fields pooled)."""
    stained = np.asarray(stained, dtype=np.float64)
    if stained.size < 500:
        raise ValueError("Control region has too little DAB-stained tissue to calibrate from.")
    return {f"p{p}": float(np.percentile(stained, p)) for p in PERCENTILES} | {"stained_pixels": int(stained.size)}


def calibration_gain(slide: dict, reference: dict, level: str = "p90", limits: tuple[float, float] = (0.33, 3.0)) -> float:
    """Multiplicative DAB gain that makes the slide's control match the reference control."""
    gain = reference[level] / max(1e-6, slide[level])
    lo, hi = limits
    if not lo <= gain <= hi:
        raise ValueError(f"Control calibration gain {gain:.2f} outside {limits}: the control itself may have failed; "
                         "the slide needs a pathologist check, not a correction.")
    return float(gain)


def apply_dab_gain(rgb: np.ndarray, gain: float, h_gain: float = 1.0) -> np.ndarray:
    """Rescale DAB (and optionally haematoxylin) concentration with the Ruifrok vectors."""
    matrix = build_stain_matrix()
    conc = deconvolve(rgb, matrix)
    conc[..., 0] *= h_gain
    conc[..., 1] *= gain
    return od_to_rgb(conc @ matrix)
