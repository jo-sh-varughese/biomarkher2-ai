"""Separate the patient's tissue from things on the glass that are not the patient.

On-slide control tissue
-----------------------
HER2 IHC slides very often carry **on-slide controls**: small round cores of
cell lines or tissue with known HER2 status (0 / 1+ / 2+ / 3+), placed apart
from the patient's section. A tumour detector cannot tell a 3+ control core
from tumour -- it *is* carcinoma -- so without this step the control's cells
are counted as the patient's and can push a HER2-0 case towards positive.
Seen on the first real HER2 whole slide tested (ACROBAT case 39).

The patient's own tumour also falls apart into many small round pieces on
the overview (tumour nests), so "small and round" alone is not enough. What
marks a control is that it stands **apart**: tissue fragments within
``group_um`` of each other are grouped into pieces, and a piece is a likely
control when it is small (equivalent diameter 0.4-3 mm), compact, far from
the main tissue, and much smaller than it.

Excluded pieces are never silently dropped: they are returned, drawn on the
overlay and listed in the flags so the pathologist can check them.
"""

from __future__ import annotations

import numpy as np


def group_pieces(tissue: np.ndarray, um_per_px: float, group_um: float = 500.0) -> np.ndarray:
    """Label map of tissue pieces: fragments closer than ``group_um`` share a label."""
    from scipy import ndimage

    if not tissue.any():
        return np.zeros(tissue.shape, dtype=np.int32)
    near = ndimage.distance_transform_edt(~tissue) <= (group_um / 2.0) / um_per_px
    labels, _ = ndimage.label(near)
    return np.where(tissue, labels, 0)


def find_control_cores(tissue: np.ndarray, um_per_px: float, group_um: float = 500.0,
                       min_diameter_mm: float = 0.4, max_diameter_mm: float = 3.0,
                       min_gap_mm: float = 1.5, max_area_ratio: float = 0.25,
                       min_compactness: float = 0.45) -> tuple[np.ndarray, list[dict]]:
    """Mask of likely on-slide control cores, and one record per core.

    Returns ``(control_mask, cores)``; ``control_mask`` is False everywhere when
    the slide has a single tissue piece (nothing to separate).
    """
    from scipy import ndimage
    from skimage import measure

    pieces = group_pieces(tissue, um_per_px, group_um)
    ids = [i for i in np.unique(pieces) if i]
    control = np.zeros(tissue.shape, dtype=bool)
    if len(ids) < 2:
        return control, []
    px_mm2 = (um_per_px / 1000.0) ** 2
    areas = {i: float((pieces == i).sum()) * px_mm2 for i in ids}
    main = max(areas, key=areas.get)
    main_dist_mm = ndimage.distance_transform_edt(pieces != main) * um_per_px / 1000.0
    cores = []
    for i in ids:
        if i == main:
            continue
        m = pieces == i
        filled = ndimage.binary_fill_holes(ndimage.binary_closing(m, iterations=2))
        props = measure.regionprops(filled.astype(np.uint8))[0]
        diameter = props.equivalent_diameter_area * um_per_px / 1000.0
        compact = 4 * np.pi * props.area / max(props.perimeter, 1.0) ** 2
        gap = float(main_dist_mm[m].min())
        if (min_diameter_mm <= diameter <= max_diameter_mm and compact >= min_compactness
                and gap >= min_gap_mm and areas[i] <= max_area_ratio * areas[main]):
            control |= m
            y, x = props.centroid
            cores.append({"centroid_overview": [int(y), int(x)], "diameter_mm": round(diameter, 2),
                          "area_mm2": round(areas[i], 2), "gap_to_main_mm": round(gap, 1),
                          "compactness": round(float(compact), 2)})
    return control, cores


def blue_cast(rgb: np.ndarray, glass_rgb) -> float:
    """How much bluer than the glass the brightest 10% of a region is (B-R units).

    Real tissue always has near-glass-coloured gaps (lumens, stroma, spaces
    between cells): measured -11..+4 on tissue and on-slide controls. Blue
    ink, pen marks and mounting-medium films tint everything, including their
    lightest pixels: measured +20..+32 (ACROBAT case 39). A tumour segmenter
    working on the haematoxylin channel sees such a film as dense
    haematoxylin, so these regions are excluded before they can be called
    tumour.
    """
    px = rgb.reshape(-1, 3).astype(np.float32)
    bright = px[px.sum(1) >= np.percentile(px.sum(1), 90)]
    g = np.asarray(glass_rgb, dtype=np.float32)
    return float((bright[:, 2].mean() - bright[:, 0].mean()) - (g[2] - g[0]))
