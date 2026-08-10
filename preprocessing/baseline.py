"""Classical DAB-threshold intensity mapping.

This module does three jobs, and it is worth being explicit about all three
because they pull in different directions:

1. It is the **pseudo-label generator** for the weakly-supervised training
   path. We have no pixel-level annotations, so initial region labels come
   from thresholding the DAB optical density.

2. It is the **experimental control**. Because the model in Phase 2 learns
   from these pseudo-labels, a good agreement score in Phase 4 could mean the
   model merely relearned these thresholds. Carrying this classical path all
   the way through to the same Phase 4 metrics is what makes the deep model's
   contribution measurable rather than assumed. If SegFormer does not beat
   this baseline, that is the finding.

3. It provides the **area-percentage machinery** that Phase 3 reuses.

The intensity classes are:
    0 background / non-tissue
    1 negative (no staining)
    2 weak (1+)
    3 moderate (2+)
    4 strong (3+)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import StainConfig
from .stains import dab_channel

CLASS_BACKGROUND = 0
CLASS_NEGATIVE = 1
CLASS_WEAK = 2
CLASS_MODERATE = 3
CLASS_STRONG = 4

NUM_CLASSES = 5

CLASS_NAMES: dict[int, str] = {
    CLASS_BACKGROUND: "background",
    CLASS_NEGATIVE: "negative",
    CLASS_WEAK: "weak (1+)",
    CLASS_MODERATE: "moderate (2+)",
    CLASS_STRONG: "strong (3+)",
}

# Tissue classes only -- background is excluded from area percentages, since
# how much glass happens to be in frame is an artifact of framing, not a
# property of the specimen.
TISSUE_CLASSES = (CLASS_NEGATIVE, CLASS_WEAK, CLASS_MODERATE, CLASS_STRONG)


@dataclass(frozen=True)
class AreaDistribution:
    """Area percentages across intensity classes, over tissue only."""

    fractions: dict[int, float]
    """Class index -> fraction of tissue area, summing to 1 (or all zero)."""

    tissue_pixels: int
    total_pixels: int

    @property
    def percentages(self) -> dict[int, float]:
        return {k: 100.0 * v for k, v in self.fractions.items()}

    @property
    def tissue_fraction(self) -> float:
        if self.total_pixels == 0:
            return 0.0
        return self.tissue_pixels / self.total_pixels

    def as_row(self) -> dict[str, float]:
        """Flatten to a dict suitable for a CSV row."""
        row: dict[str, float] = {
            "tissue_pixels": float(self.tissue_pixels),
            "total_pixels": float(self.total_pixels),
            "tissue_fraction": self.tissue_fraction,
        }
        for cls in TISSUE_CLASSES:
            row[f"pct_{CLASS_NAMES[cls].split(' ')[0]}"] = self.percentages.get(
                cls, 0.0
            )
        return row


def intensity_map(
    rgb: np.ndarray,
    tissue_mask: np.ndarray,
    config: StainConfig | None = None,
) -> np.ndarray:
    """Classify each pixel into an intensity class from its DAB density.

    Returns an HxW uint8 array of class indices. Non-tissue pixels are always
    class 0 regardless of their DAB value, so that unstained glass cannot be
    mistaken for negative tissue.
    """
    cfg = config or StainConfig()
    dab = dab_channel(rgb, background_intensity=cfg.background_intensity)
    mask = np.asarray(tissue_mask, dtype=bool)
    if mask.shape != dab.shape:
        raise ValueError(
            f"Tissue mask shape {mask.shape} does not match image shape {dab.shape}"
        )

    weak, moderate, strong = cfg.thresholds()
    if not (weak < moderate < strong):
        raise ValueError(
            "DAB thresholds must be strictly increasing, got "
            f"weak={weak}, moderate={moderate}, strong={strong}"
        )

    classes = np.full(dab.shape, CLASS_BACKGROUND, dtype=np.uint8)
    classes[mask] = CLASS_NEGATIVE
    classes[mask & (dab >= weak)] = CLASS_WEAK
    classes[mask & (dab >= moderate)] = CLASS_MODERATE
    classes[mask & (dab >= strong)] = CLASS_STRONG
    return classes


def area_distribution(classes: np.ndarray) -> AreaDistribution:
    """Compute the fraction of tissue area in each intensity class."""
    array = np.asarray(classes)
    total = int(array.size)
    tissue = int(np.isin(array, TISSUE_CLASSES).sum())
    if tissue == 0:
        return AreaDistribution(
            fractions={cls: 0.0 for cls in TISSUE_CLASSES},
            tissue_pixels=0,
            total_pixels=total,
        )
    fractions = {
        cls: float((array == cls).sum()) / tissue for cls in TISSUE_CLASSES
    }
    return AreaDistribution(
        fractions=fractions, tissue_pixels=tissue, total_pixels=total
    )


def dab_statistics(
    rgb: np.ndarray,
    tissue_mask: np.ndarray,
    config: StainConfig | None = None,
) -> dict[str, float]:
    """Summary statistics of DAB optical density over tissue pixels.

    This is the quantity the sanity check uses to verify that deconvolution
    behaves sensibly: mean tissue DAB density should increase monotonically
    across the 0 -> 1+ -> 2+ -> 3+ classes. If it does not, either the
    deconvolution or the dataset labels are wrong, and everything downstream
    inherits the error.
    """
    cfg = config or StainConfig()
    dab = dab_channel(rgb, background_intensity=cfg.background_intensity)
    mask = np.asarray(tissue_mask, dtype=bool)
    if not mask.any():
        return {
            "dab_mean": 0.0,
            "dab_median": 0.0,
            "dab_p90": 0.0,
            "dab_p99": 0.0,
            "dab_max": 0.0,
        }
    values = dab[mask]
    return {
        "dab_mean": float(values.mean()),
        "dab_median": float(np.median(values)),
        "dab_p90": float(np.percentile(values, 90)),
        "dab_p99": float(np.percentile(values, 99)),
        "dab_max": float(values.max()),
    }
