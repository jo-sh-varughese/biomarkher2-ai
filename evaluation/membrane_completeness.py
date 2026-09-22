"""Offline exploratory membrane-morphology analysis.

This module is evaluation-only. It is not connected to app/ and does not
produce a clinical HER2 interpretation.

The analysis treats membrane completeness as an exploratory morphology proxy
for DAB-stained components. It measures angular continuity of a peripheral
stained structure and penalizes structures that occupy the interior like a
solid blob.

This is not a pathologist annotation or a clinical membrane-completeness
measurement.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage


@dataclass(frozen=True)
class ComponentFeatures:
    """Morphology measurements for one connected stained component."""

    area: int
    boundary_continuity: float
    boundary_enrichment: float
    ringness: float
    completeness: float


def _inner_boundary(component: np.ndarray) -> np.ndarray:
    """Return pixels on the inner edge of a binary component."""
    eroded = ndimage.binary_erosion(
        component,
        structure=np.ones((3, 3)),
    )
    return component & ~eroded


def _inner_core(component: np.ndarray) -> np.ndarray:
    """Return a conservative interior region."""
    return ndimage.binary_erosion(
        component,
        structure=np.ones((3, 3)),
        iterations=2,
    )


def _radial_continuity(
    component: np.ndarray,
    bins: int = 72,
) -> float:
    """Measure angular continuity of the outer component boundary."""
    ys, xs = np.nonzero(component)

    if len(xs) == 0:
        return 0.0

    boundary = _inner_boundary(component)
    by, bx = np.nonzero(boundary)

    if len(bx) == 0:
        return 0.0

    cy = float(np.mean(ys))
    cx = float(np.mean(xs))

    angles = np.arctan2(by - cy, bx - cx)
    indices = ((angles + np.pi) / (2.0 * np.pi) * bins).astype(int)
    indices = np.clip(indices, 0, bins - 1)

    occupied = np.zeros(bins, dtype=bool)
    occupied[np.unique(indices)] = True

    return float(np.mean(occupied))


def _boundary_enrichment(
    component: np.ndarray,
    dab: np.ndarray | None,
) -> float:
    """Estimate peripheral DAB enrichment relative to the center.

    The comparison is made between DAB on the component boundary and DAB in
    a central region estimated from the component centroid. This avoids
    treating the stained membrane itself as the ``core`` of the structure.
    """
    if dab is None:
        return 0.5

    boundary = _inner_boundary(component)

    if not boundary.any():
        return 0.5

    ys, xs = np.nonzero(component)
    by, bx = np.nonzero(boundary)

    cy = float(np.mean(ys))
    cx = float(np.mean(xs))

    boundary_radius = np.sqrt(
        (by - cy) ** 2 + (bx - cx) ** 2
    )

    if len(boundary_radius) == 0:
        return 0.5

    # Use a conservative central radius. For a membrane ring this samples
    # the unstained interior; for a filled disk it samples stained tissue.
    central_radius = float(np.percentile(boundary_radius, 35.0))

    yy, xx = np.indices(component.shape)
    radius = np.sqrt(
        (yy - cy) ** 2 + (xx - cx) ** 2
    )

    center_region = radius <= central_radius

    if not center_region.any():
        return 0.5

    boundary_mean = float(np.mean(dab[boundary]))
    center_mean = float(np.mean(dab[center_region]))

    difference = boundary_mean - center_mean

    # Positive values indicate peripheral enrichment.
    return float(1.0 / (1.0 + np.exp(-8.0 * difference)))

def _ringness(component: np.ndarray) -> float:
    """Estimate whether staining is peripheral rather than solid."""
    area = int(component.sum())

    if area == 0:
        return 0.0

    boundary = _inner_boundary(component)
    core = _inner_core(component)

    boundary_area = float(boundary.sum())
    core_area = float(core.sum())

    if core_area == 0:
        return 1.0

    ratio = boundary_area / max(1.0, boundary_area + core_area)

    # Thin peripheral structures have high boundary/core ratio.
    # Solid regions have relatively more interior pixels.
    return float(np.clip(ratio / 0.5, 0.0, 1.0))


def component_features(
    component: np.ndarray,
    dab: np.ndarray | None = None,
) -> ComponentFeatures:
    """Extract exploratory membrane-morphology features."""
    component = np.asarray(component, dtype=bool)

    if component.ndim != 2:
        raise ValueError("component must be a 2-D boolean array")

    area = int(component.sum())

    if area == 0:
        return ComponentFeatures(
            area=0,
            boundary_continuity=0.0,
            boundary_enrichment=0.5,
            ringness=0.0,
            completeness=0.0,
        )

    continuity = _radial_continuity(component)
    enrichment = _boundary_enrichment(component, dab)
    ringness = _ringness(component)

    boundary_signal = float(
        np.clip(
            2.0 * (enrichment - 0.5),
            0.0,
            1.0,
        )
    )

    completeness = float(
        np.clip(
            continuity * ringness * boundary_signal,
            0.0,
            1.0,
        )
    )

    return ComponentFeatures(
        area=area,
        boundary_continuity=continuity,
        boundary_enrichment=enrichment,
        ringness=ringness,
        completeness=completeness,
    )


def connected_components(
    mask: np.ndarray,
    min_area: int = 20,
) -> list[np.ndarray]:
    """Return sufficiently large connected components."""
    mask = np.asarray(mask, dtype=bool)

    if mask.ndim != 2:
        raise ValueError("mask must be 2-D")

    if min_area < 1:
        raise ValueError("min_area must be positive")

    labels, count = ndimage.label(
        mask,
        structure=np.ones((3, 3)),
    )

    components: list[np.ndarray] = []

    for label_id in range(1, count + 1):
        component = labels == label_id

        if int(component.sum()) >= min_area:
            components.append(component)

    return components


def summarize_components(
    mask: np.ndarray,
    dab: np.ndarray | None = None,
    min_area: int = 20,
) -> list[ComponentFeatures]:
    """Measure every sufficiently large stained component."""
    return [
        component_features(component, dab=dab)
        for component in connected_components(
            mask,
            min_area=min_area,
        )
    ]
