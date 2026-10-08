"""Cell-level HER2 membrane analysis: the evidence a pathologist scores from.

ASCO/CAP scores HER2 IHC on the percentage of (invasive tumour) CELLS showing
membrane staining of a given completeness and intensity (Wolff et al., J Clin
Oncol 2018; reaffirmed 2023). Pixel-area percentages do not say that, so this
module works cell by cell:

1. **Nuclei** -- haematoxylin channel (colour deconvolution), smoothed,
   thresholded within tissue, touching nuclei split by a distance-transform
   watershed.
2. **Cells** -- each nucleus grown outward to its cell territory
   (``expand_labels``), stopping where it meets a neighbour.
3. **Membrane** -- the outer ring of each territory. Its DAB optical density
   is read around the circumference in angular sectors, giving
   * *completeness*: fraction of sectors with DAB at or above the weak
     threshold (circumferential = complete);
   * *intensity*: DAB level of the stained membrane (weak / moderate /
     strong, the project's calibrated OD cut points);
   * *cytoplasmic DAB*: staining inside the cell but off the membrane (a
     pattern ASCO/CAP does not count as membrane staining).
4. **Cell category** (ASCO/CAP wording):
   * 3+  complete, intense (strong) membrane staining
   * 2+  complete, weak-to-moderate staining -- or incomplete but
         moderate/strong (flagged: an atypical pattern that needs review)
   * 1+  incomplete, faint/barely perceptible staining
   * 0   no membrane staining
5. **Field category** by the ASCO/CAP 10% rule, with HER2-low (1+, or 2+
   ISH-negative) and HER2-ultralow (0 with faint incomplete staining in >0%
   and <=10% of cells) noted, since they now decide eligibility for
   trastuzumab deruxtecan.

LIMITS, stated in every result: tumour cells are not yet separated from
stroma, lymphocytes or normal epithelium (all detected cells count), and the
completeness / intensity cut points are provisional. This is measured
evidence for the pathologist, not the pathologist's score.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from preprocessing.stains import deconvolve

CELL_CATEGORIES = ("0", "1+", "2+", "3+")
CELL_COLORS = {"0": (110, 130, 160), "1+": (232, 196, 60), "2+": (236, 128, 40), "3+": (200, 30, 40)}

CELL_CAVEAT = (
    "Cell-level measurement counts every detected cell in tissue: tumour cells are not yet separated from "
    "stroma, lymphocytes or normal ducts, and the membrane completeness and intensity cut points are "
    "provisional. Read the percentages as measured evidence, not as the final tumour-cell percentage."
)


@dataclass(frozen=True)
class CellParams:
    """Sizes in pixels at the training scale (HER2-IHC-40x, ~0.24 um/px). Use ``scaled`` for other scanners."""

    nucleus_sigma: float = 2.0
    min_nucleus_area: int = 400         # ~23 um^2
    max_nucleus_area: int = 25000
    split_min_distance: int = 20
    cell_expand: int = 70               # grow to meet neighbours: the shared border is where membranes are
    membrane_width: int = 6
    sectors: int = 24
    complete_fraction: float = 0.75     # share of sectors stained for "complete / circumferential"
    any_fraction: float = 0.15          # share of sectors stained for "some membrane staining"
    rule_percent: float = 10.0          # ASCO/CAP: >10% of cells
    # Cell-level membrane DAB cut points (OD). None -> the pixel-level weak/strong thresholds.
    membrane_faint: float | None = None
    membrane_strong: float | None = None
    min_cells: int = 100                # fewer cells: percentages too unstable to lean on

    def scaled(self, factor: float) -> "CellParams":
        """Parameters for an image whose pixels are ``factor`` times smaller in microns."""
        from dataclasses import replace

        return replace(self, nucleus_sigma=self.nucleus_sigma * factor,
                       min_nucleus_area=max(8, int(self.min_nucleus_area * factor ** 2)),
                       max_nucleus_area=int(self.max_nucleus_area * factor ** 2),
                       split_min_distance=max(2, int(self.split_min_distance * factor)),
                       cell_expand=max(3, int(self.cell_expand * factor)),
                       membrane_width=max(1, int(round(self.membrane_width * factor))))


def detect_nuclei(h: np.ndarray, tissue: np.ndarray, p: CellParams, d: np.ndarray | None = None) -> np.ndarray:
    """Labelled nuclei (0 = background)."""
    from skimage.feature import peak_local_max
    from skimage.filters import threshold_otsu
    from skimage.segmentation import watershed

    hs = ndimage.gaussian_filter(h, p.nucleus_sigma)
    values = hs[tissue]
    if values.size < 500 or float(np.ptp(values)) < 1e-3:
        return np.zeros(h.shape, dtype=np.int32)
    thr = max(0.12, float(threshold_otsu(values)))
    mask = tissue & (hs > thr)
    if d is not None:
        # Nuclei are haematoxylin-dominant; strongly stained DAB membranes leak
        # into the H channel and must not be mistaken for nuclei.
        mask &= hs > 1.1 * ndimage.gaussian_filter(d, p.nucleus_sigma)
    mask = ndimage.binary_opening(mask, iterations=2)
    mask = ndimage.binary_fill_holes(mask)
    labels, _ = ndimage.label(mask)
    sizes = np.bincount(labels.ravel())
    keep = (sizes >= p.min_nucleus_area) & (sizes <= p.max_nucleus_area * 3)
    keep[0] = False
    mask = keep[labels]
    if not mask.any():
        return np.zeros(h.shape, dtype=np.int32)
    distance = ndimage.distance_transform_edt(mask)
    peaks = peak_local_max(distance, min_distance=p.split_min_distance, labels=ndimage.label(mask)[0], exclude_border=False)
    markers = np.zeros(h.shape, dtype=np.int32)
    markers[tuple(peaks.T)] = np.arange(1, len(peaks) + 1)
    nuclei = watershed(-distance, markers, mask=mask)
    sizes = np.bincount(nuclei.ravel())
    bad = (sizes < p.min_nucleus_area) | (sizes > p.max_nucleus_area)
    bad[0] = False
    nuclei[bad[nuclei]] = 0
    return nuclei


def detect_cells_from_membranes(d: np.ndarray, tissue: np.ndarray, p: CellParams) -> np.ndarray:
    """Cell interiors found from a strong membrane network (0 = background).

    For strongly positive fields: there the brown stain covers the cytoplasm
    and hides the nuclei, so the nucleus-first detector finds almost nothing
    (seen 2026-10-02 on a textbook 3+ image: 0 cells). The membranes are the
    darkest DAB structures, so cells are the spaces they enclose. Each interior
    then plays the part of a nucleus and the usual membrane measurement reads
    the ring around it.
    """
    from skimage.feature import peak_local_max
    from skimage.filters import threshold_multiotsu
    from skimage.measure import regionprops
    from skimage.segmentation import watershed

    ds = ndimage.gaussian_filter(d, 1.0 * p.nucleus_sigma / 2.0)
    if tissue.sum() < 500:
        return np.zeros(d.shape, dtype=np.int32)
    vals = ds[tissue]
    # A uniform field (a flat colour fill, or a field saturated with stain) has
    # no three-level structure to split; there are no membranes to find.
    if float(np.ptp(vals)) < 1e-3:
        return np.zeros(d.shape, dtype=np.int32)
    try:
        _, t2 = threshold_multiotsu(vals, classes=3)
    except ValueError:
        return np.zeros(d.shape, dtype=np.int32)
    memb = tissue & (ds > t2)
    memb = ndimage.binary_opening(memb, iterations=1) | (tissue & (ds > t2 * 1.15))
    memb = ndimage.binary_closing(memb, iterations=2)
    inside = tissue & ~memb
    dist = ndimage.distance_transform_edt(inside)
    peaks = peak_local_max(dist, min_distance=max(3, int(p.split_min_distance * 0.6)),
                           threshold_abs=max(2.0, p.membrane_width), labels=ndimage.label(inside)[0], exclude_border=False)
    if not len(peaks):
        return np.zeros(d.shape, dtype=np.int32)
    markers = np.zeros(d.shape, dtype=np.int32)
    markers[tuple(peaks.T)] = np.arange(1, len(peaks) + 1)
    cells = watershed(-dist, markers, mask=inside)
    keep = np.zeros(int(cells.max()) + 1, dtype=bool)
    for r in regionprops(cells):
        keep[r.label] = (p.min_nucleus_area * 1.5 <= r.area <= p.max_nucleus_area) and r.solidity >= 0.8
    out, _ = ndimage.label(keep[cells])
    return out.astype(np.int32)


def _strong_membrane_network(d: np.ndarray, tissue: np.ndarray, cut: float) -> bool:
    """True when >= 5% of the tissue carries DAB above ``cut``: a well-stained membrane network."""
    return bool(tissue.any()) and float((d[tissue] >= cut).mean()) >= 0.05


def analyze_cells(rgb: np.ndarray, tissue: np.ndarray, thresholds: tuple[float, float, float],
                  params: CellParams | None = None) -> dict:
    """Per-cell membrane measurements and the ASCO/CAP-style field summary."""
    from skimage.segmentation import expand_labels, find_boundaries

    p = params or CellParams()
    weak, moderate, strong = thresholds
    conc = deconvolve(rgb)
    h, d = conc[..., 0], conc[..., 1]
    nuclei = detect_nuclei(h, tissue, p, d)
    method, expand = "nuclei", p.cell_expand
    n_nuclei = int(len(np.unique(nuclei)) - 1)
    network_cut = ((p.membrane_faint or weak) + (p.membrane_strong or strong)) / 2  # a membrane network, not "strong"
    if n_nuclei < p.min_cells and _strong_membrane_network(d, tissue, network_cut):
        interiors = detect_cells_from_membranes(d, tissue, p)
        if int(interiors.max()) > 2 * max(1, n_nuclei):
            nuclei, method, expand = interiors, "membranes", max(3, p.membrane_width * 3)
    cells = expand_labels(nuclei, distance=expand)
    cells[~tissue] = 0
    ring = find_boundaries(cells, mode="inner")
    ring = ndimage.binary_dilation(ring, iterations=max(0, p.membrane_width - 1)) & (cells > 0) & (nuclei == 0)
    n = int(cells.max())
    records = []
    if n:
        # Membrane DAB is read from the whole territory outside the nucleus,
        # sector by sector (the strongest DAB in each direction). Between
        # neighbours that is the shared border, where membranes are; for an
        # isolated cell it finds the membrane wherever it lies inside the
        # territory instead of assuming it sits at the territory's edge.
        outside_nucleus = (cells > 0) & ~ndimage.binary_dilation(nuclei > 0, iterations=3)
        ys, xs = np.nonzero(outside_nucleus)
        ids = cells[ys, xs]
        centroids = ndimage.center_of_mass(np.ones_like(nuclei), nuclei, index=np.arange(1, n + 1))
        cyto = (cells > 0) & ~ring & (nuclei == 0)
        cyto_sum = ndimage.sum(d, labels=np.where(cyto, cells, 0), index=np.arange(1, n + 1))
        cyto_cnt = ndimage.sum(cyto, labels=np.where(cyto, cells, 0), index=np.arange(1, n + 1))
        order = np.argsort(ids, kind="stable")
        ys, xs, ids = ys[order], xs[order], ids[order]
        bounds = np.searchsorted(ids, np.arange(1, n + 2))
        for k in range(n):
            a, b = bounds[k], bounds[k + 1]
            if b - a < 8:
                continue
            cy, cx = centroids[k]
            if not np.isfinite(cy):
                continue
            yy, xx = ys[a:b], xs[a:b]
            dv = d[yy, xx]
            sector = ((np.arctan2(yy - cy, xx - cx) + np.pi) / (2 * np.pi) * p.sectors).astype(int) % p.sectors
            best = np.full(p.sectors, np.nan)
            present = np.bincount(sector, minlength=p.sectors) > 0
            best[present] = 0.0
            np.fmax.at(best, sector, dv)
            records.append({"id": k + 1, "y": float(cy), "x": float(cx), "sector_max": best,
                            "cytoplasm_od": round(float(cyto_sum[k] / max(1.0, cyto_cnt[k])), 3)})
    for r in records:
        classify_cell(r, p, thresholds)
    summary = summarize(records, p)
    summary["detection"] = method
    if method == "membranes":
        summary["flags"] = summary.get("flags", []) + [
            "Nuclei hidden by strong staining: cells were found from their stained membranes instead. "
            "Cells without a visible closed membrane are not counted, so check the 0/1+ share by eye."]
    return {"cells": records, "summary": summary, "labels": cells, "nuclei": nuclei, "ring": ring}


def classify_cell(r: dict, p: CellParams, thresholds: tuple[float, float, float]) -> dict:
    """(Re)apply the category rules to one cell's per-sector membrane DAB maxima."""
    weak, moderate, strong = thresholds
    faint = p.membrane_faint if p.membrane_faint is not None else weak
    strong_cut = p.membrane_strong if p.membrane_strong is not None else strong
    moderate_cut = (faint + strong_cut) / 2 if p.membrane_strong is not None else moderate
    best = r["sector_max"]
    valid = best[~np.isnan(best)]
    completeness = float((valid >= faint).mean()) if valid.size else 0.0
    stained = valid[valid >= faint]
    intensity = float(np.median(stained)) if stained.size else (float(np.median(valid)) if valid.size else 0.0)
    level = "strong" if intensity >= strong_cut else "moderate" if intensity >= moderate_cut else "weak" if intensity >= faint else "none"
    if completeness >= p.complete_fraction and level == "strong":
        cat, atypical = "3+", False
    elif completeness >= p.complete_fraction and level in ("weak", "moderate"):
        cat, atypical = "2+", False
    elif completeness >= p.any_fraction and level in ("moderate", "strong"):
        cat, atypical = "2+", True
    elif completeness >= p.any_fraction and level == "weak":
        cat, atypical = "1+", False
    else:
        cat, atypical = "0", False
    r.update({"completeness": round(completeness, 3), "membrane_od": round(intensity, 3), "level": level,
              "category": cat, "atypical": atypical})
    return r


def public_cells(records: list[dict]) -> list[dict]:
    """Per-cell records without the internal sector array (JSON-safe)."""
    return [{k: v for k, v in r.items() if k != "sector_max"} for r in records]


def summarize(records: list[dict], p: CellParams | None = None) -> dict:
    p = p or CellParams()
    total = len(records)
    counts = {c: sum(r["category"] == c for r in records) for c in CELL_CATEGORIES}
    pct = {c: (100.0 * counts[c] / total if total else 0.0) for c in CELL_CATEGORIES}
    at_least_2 = pct["2+"] + pct["3+"]
    at_least_1 = at_least_2 + pct["1+"]
    if pct["3+"] > p.rule_percent:
        category, rule = "3+", f"{pct['3+']:.1f}% of cells show complete, intense membrane staining (>{p.rule_percent:.0f}%)"
    elif at_least_2 > p.rule_percent:
        category, rule = "2+", f"{at_least_2:.1f}% of cells show complete weak-to-moderate (or stronger) staining (>{p.rule_percent:.0f}%)"
    elif at_least_1 > p.rule_percent:
        category, rule = "1+", f"{at_least_1:.1f}% of cells show faint, incomplete membrane staining (>{p.rule_percent:.0f}%)"
    else:
        category, rule = "0", f"only {at_least_1:.1f}% of cells show any membrane staining (<={p.rule_percent:.0f}%)"
    her2_low = category == "1+"
    ultralow = category == "0" and 0.0 < at_least_1 <= p.rule_percent
    flags = []
    if total < p.min_cells:
        flags.append(f"Only {total} cells detected: cell percentages are unstable below {p.min_cells}.")
    atypical = sum(r["atypical"] for r in records)
    if total and atypical / total > 0.05:
        flags.append(f"{100 * atypical / total:.1f}% of cells show intense but incomplete membrane staining "
                     "(an atypical pattern; ASCO/CAP advises careful review).")
    cyto = [r for r in records if r["cytoplasm_od"] >= 0.5 and r["category"] in ("0", "1+")]
    if total and len(cyto) / total > 0.10:
        flags.append(f"{100 * len(cyto) / total:.1f}% of cells show cytoplasmic DAB without membrane staining "
                     "(not counted as membrane positivity).")
    return {"cells_measured": total, "counts": counts, "percent": {k: round(v, 1) for k, v in pct.items()},
            "percent_at_least_1plus": round(at_least_1, 1), "percent_at_least_2plus": round(at_least_2, 1),
            "field_category": category, "rule_applied": rule, "her2_low": her2_low, "her2_ultralow": ultralow,
            "flags": flags, "caveat": CELL_CAVEAT}


def overlay_cells(rgb: np.ndarray, result: dict, alpha: float = 0.85) -> np.ndarray:
    """Membranes painted in each cell's category colour over a lightened field."""
    out = (rgb.astype(np.float32) * 0.55 + 255 * 0.45)
    cells, ring = result["labels"], result["ring"]
    colour = np.zeros((int(cells.max()) + 1, 3), dtype=np.float32)
    for r in result["cells"]:
        colour[r["id"]] = CELL_COLORS[r["category"]]
    painted = ring & (cells > 0)
    out[painted] = out[painted] * (1 - alpha) + colour[cells[painted]] * alpha
    nuc_edge = ndimage.binary_dilation(result["nuclei"] > 0) & ~(result["nuclei"] > 0)
    out[nuc_edge] = out[nuc_edge] * 0.4 + np.array([40, 40, 90]) * 0.6
    return np.clip(out, 0, 255).astype(np.uint8)


def load_cell_params(path: str | None = "configs/cell_params.json", scale: float = 1.0) -> CellParams:
    """Calibrated parameters (scripts/calibrate_cells.py), scaled for the site's microns-per-pixel.

    ``scale`` = training-site um/px / this site's um/px (pixels are bigger -> smaller structures).
    Falls back to the built-in defaults when no calibration file exists.
    """
    import json
    from dataclasses import fields
    from pathlib import Path

    params = CellParams()
    if path and Path(path).is_file():
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {f.name for f in fields(CellParams)}
        params = CellParams(**{k: v for k, v in raw.items() if k in known})
    return params.scaled(scale) if abs(scale - 1.0) > 1e-6 else params
