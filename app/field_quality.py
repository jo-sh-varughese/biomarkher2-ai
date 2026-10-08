"""Is this image a usable HER2 IHC field? -- the gate in front of every grade.

The models and the cell rule always return *some* grade, even for blank glass,
noise, an H&E section or a nuclear stain. This module decides, before any
grade is shown, whether the field can be scored at all, and if not says why.
A field that fails any blocking check is reported as "Not assessable" with its
reasons: no AI pre-score, no cell grade, no ISH suggestion.

Two kinds of output:

* ``measure_image(rgb)`` -- cheap colour/texture measurements on the raw pixels
  (no model), plus an artefact mask (marker/ink colours, black ink, flat
  graphics) that is removed from the tissue before anything is measured.
* ``assess(...)`` -- turns the measurements, plus the tissue fraction, the cell
  count, the focus score and the DAB pattern found later in the pipeline, into
  a verdict with reasons, each reason tagged "block" (not assessable) or
  "caution" (assessable, shown as a caution).

Every threshold below was set from real images (scripts/calibrate_field_quality.py,
results in docs/FIELD_QUALITY.md): HER2 IHC fields from two sites and one
whole slide must pass; H&E sections, a nuclear (Ki-67) IHC stain and synthetic
failures must not.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

# ---------------------------------------------------------------- thresholds
MIN_SIDE_PX = 256                 # smaller crops hold too few cells to score
MAX_PIXELS = 64_000_000           # single-field uploads; larger images belong in whole-slide analysis
DARK_FRACTION_BLOCK = 0.5         # share of near-black pixels (all channels < 30)
COLOUR_SPREAD_BLOCK = 2.0         # mean (max-min channel) over stained pixels; greyscale 0, real IHC >= 5
NOISE_BLOCK = 40.0                # mean |neighbour difference| of luminance; real fields < 20, uniform noise ~85
FLAT_FRACTION_BLOCK = 0.25        # share of stained 8x8 blocks with zero variation (graphics, not a scan)
FLAT_FRACTION_CAUTION = 0.05      # real whole-slide fields reach 0.037
STRUCTURE_BLOCK = 3.0             # luminance s.d. inside tissue; a flat colour fill ~0, real IHC >= 6
EOSIN_BLOCK = 0.05                # eosin share of stain: HER2 IHC <= 0.009 at two sites, H&E slide fields >= 0.057
EOSIN_CAUTION = 0.03
FOREIGN_BLOCK = 0.10              # share of tissue in marker colours (green/cyan); ink, annotation
FOREIGN_CAUTION = 0.005
INK_CAUTION = 0.01                # share of tissue in near-black neutral (black ink, pigment, debris)
NUCLEAR_PATTERN_BLOCK = 0.30      # share of DAB in filled, round, nucleus-sized blobs -> nuclear marker (ER/PR/Ki-67)
NUCLEAR_PATTERN_CAUTION = 0.20
NUCLEAR_PATTERN_MIN_DAB = 0.01    # ... only judged when DAB covers at least 1% of the image
TISSUE_BLOCK, TISSUE_CAUTION = 5.0, 20.0          # percent of the frame
CELLS_BLOCK, CELLS_CAUTION = 30, 100
EDGE_DAB_CAUTION = 0.5            # share of strong DAB lying in the outer tissue rim

BLOCK, CAUTION = "block", "caution"


def _lum(rgb: np.ndarray) -> np.ndarray:
    return rgb.astype(np.float32) @ np.array([0.299, 0.587, 0.114], dtype=np.float32)


def _hed(rgb: np.ndarray) -> np.ndarray:
    from skimage.color import rgb2hed

    return np.clip(rgb2hed(rgb.astype(np.float32) / 255.0), 0, None)


def _hue_sat_val(rgb: np.ndarray):
    from skimage.color import rgb2hsv

    hsv = rgb2hsv(rgb)
    return hsv[..., 0] * 360.0, hsv[..., 1], hsv[..., 2]


def white_reference(rgb: np.ndarray) -> np.ndarray:
    """Per-channel brightness of the glass: the 99th percentile of each channel,
    floored at 180 so an image with no glass at all is not rescaled."""
    ref = np.percentile(rgb.reshape(-1, 3), 99, axis=0).astype(np.float32)
    return np.clip(ref, 180, 255)


def stained_mask(rgb: np.ndarray) -> np.ndarray:
    """Pixels that absorb light relative to the glass (mean optical density > 0.15).

    Measured against the image's own glass level, not pure white: some
    scanners (BCI) render empty glass mid-grey, which an absolute cut would
    count as tissue.
    """
    ref = white_reference(rgb)
    od = -np.log(np.clip(rgb.astype(np.float32), 1, 255) / ref)
    return od.mean(-1) > 0.15


def artefact_mask(rgb: np.ndarray, hue=None, sat=None, val=None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(foreign colour, near-black neutral, flat graphics) masks.

    Foreign: saturated green/cyan -- no histological stain in a HER2 IHC field
    has that hue (haematoxylin is blue-violet, DAB brown, eosin pink), but
    marking ink, pen and on-screen annotations do. Near-black neutral: black
    ink, pigment, folds. Flat: 8x8 blocks of stained pixels with no variation at
    all, which a scanner sensor never produces (screenshots, overlays, fills).
    """
    if hue is None:
        hue, sat, val = _hue_sat_val(rgb)
    foreign = (hue >= 75) & (hue <= 190) & (sat > 0.30) & (val > 0.15)
    neutral_dark = (rgb.max(-1) < 60) & (sat < 0.35)
    h, w = rgb.shape[:2]
    bh, bw = h // 8, w // 8
    flat = np.zeros((h, w), dtype=bool)
    if bh and bw:
        blocks = rgb[: bh * 8, : bw * 8].reshape(bh, 8, bw, 8, 3).astype(np.int16)
        span = (blocks.max(axis=(1, 3)) - blocks.min(axis=(1, 3))).max(-1)
        meanv = blocks.mean(axis=(1, 3, 4))
        flat_b = (span == 0) & (meanv < 235)
        flat[: bh * 8, : bw * 8] = np.repeat(np.repeat(flat_b, 8, 0), 8, 1)
    return foreign, neutral_dark, flat


def nuclear_pattern(dab: np.ndarray, valid: np.ndarray, dab_threshold: float = 0.15) -> tuple[float, float]:
    """(share of DAB area in filled, round, nucleus-sized blobs; DAB share of the image).

    HER2 is membranous: its DAB forms rings and networks. Nuclear markers
    (ER, PR, Ki-67) stain whole nuclei: filled, compact, round blobs.
    Calibrated on HER2 fields (max 0.16 at two sites) and Ki-67 images (median 0.41).
    """
    from skimage.measure import label, regionprops

    d = ndimage.gaussian_filter(dab, 1.0)
    pos = (d > dab_threshold) & valid
    total = int(pos.sum())
    if total == 0:
        return 0.0, 0.0
    blob = 0
    for r in regionprops(label(pos)):
        if 30 <= r.area <= 8000 and r.solidity >= 0.85 and r.eccentricity <= 0.95:
            blob += r.area
    return blob / total, total / pos.size


def measure_image(rgb: np.ndarray) -> dict:
    """Raw-pixel measurements and the artefact mask (no model involved)."""
    rgb = np.asarray(rgb, dtype=np.uint8)
    h, w = rgb.shape[:2]
    hue, sat, val = _hue_sat_val(rgb)
    stained = stained_mask(rgb)
    lum = _lum(rgb)
    foreign, neutral_dark, flat = artefact_mask(rgb, hue, sat, val)
    n_st = max(1, int(stained.sum()))
    spread = (rgb.max(-1).astype(np.int16) - rgb.min(-1).astype(np.int16))
    hed = _hed(rgb)
    usable = stained & ~foreign & ~neutral_dark & ~flat
    tot = hed[..., 0] + hed[..., 1] + hed[..., 2]
    eos = float(hed[..., 1][usable].sum() / max(1e-6, tot[usable].sum())) if usable.any() else 0.0
    noise = float(np.abs(np.diff(lum, axis=1)).mean()) if w > 1 else 0.0
    nuc_frac, dab_share = nuclear_pattern(hed[..., 2], ~(foreign | neutral_dark | flat))
    return {
        "width": int(w), "height": int(h),
        "stained_fraction": float(stained.mean()),
        "dark_fraction": float((rgb.max(-1) < 30).mean()),
        "colour_spread": float(spread[stained].mean()) if stained.any() else 0.0,
        "noise": noise,
        "flat_fraction": float(flat[stained].mean()) if stained.any() else 0.0,
        "structure": float(lum[usable].std()) if usable.sum() > 100 else 0.0,
        "eosin_share": eos,
        "foreign_fraction": float(foreign[stained].sum() / n_st),
        "ink_fraction": float(neutral_dark[stained].sum() / n_st),
        "nuclear_pattern": nuc_frac,
        "dab_share": dab_share,
        "artefact_mask": foreign | neutral_dark | flat,
    }


def edge_dab_share(dab: np.ndarray, tissue: np.ndarray, rim_px: int = 12, threshold: float = 0.35) -> float | None:
    """Share of strong DAB lying in the outer rim of the tissue (edge artefact pattern)."""
    strong = (ndimage.gaussian_filter(dab, 1.0) > threshold) & tissue
    if strong.sum() < 500 or tissue.mean() > 0.95:
        return None
    rim = tissue & ~ndimage.binary_erosion(tissue, iterations=rim_px)
    if rim.sum() > 0.4 * tissue.sum():
        return None
    return float((strong & rim).sum() / strong.sum())


def _reason(code: str, level: str, text: str) -> dict:
    return {"code": code, "level": level, "text": text}


def assess(m: dict, tissue_percent: float | None = None, n_cells: int | None = None,
           focus: float | None = None, edge_share: float | None = None,
           excluded_percent: float = 0.0, specimen: str | None = None) -> dict:
    """Verdict on one field: assessable or not, and why."""
    from app.decision import FOCUS_FAIL, FOCUS_WARN

    r: list[dict] = []
    if min(m["width"], m["height"]) < MIN_SIDE_PX:
        r.append(_reason("too_small", BLOCK, f"Image is {m['width']}x{m['height']} px; at least {MIN_SIDE_PX} px per side is "
                                             "needed for enough cells to score."))
    if m["dark_fraction"] > DARK_FRACTION_BLOCK:
        r.append(_reason("too_dark", BLOCK, "Most of the image is black: it is under-exposed, inverted or not a brightfield scan."))
    if m["noise"] > NOISE_BLOCK:
        r.append(_reason("noise", BLOCK, "The image is dominated by pixel noise and does not look like a microscopy field."))
    if m["flat_fraction"] > FLAT_FRACTION_BLOCK:
        r.append(_reason("graphics", BLOCK, "Large areas are flat synthetic colour (a screenshot, drawing or overlay), not a scan."))
    elif m["flat_fraction"] > FLAT_FRACTION_CAUTION:
        r.append(_reason("graphics", CAUTION, "Parts of the image are flat synthetic colour (annotations, labels or overlays); "
                                              "they were excluded from the measurement."))
    if m.get("stained_fraction", 0) > 0.01 and m["colour_spread"] < COLOUR_SPREAD_BLOCK:
        r.append(_reason("greyscale", BLOCK, "The image has no colour (greyscale or monochrome): brown HER2 staining "
                                             "cannot be separated from the blue counterstain."))
    if tissue_percent is not None and tissue_percent >= TISSUE_BLOCK and m["structure"] < STRUCTURE_BLOCK:
        r.append(_reason("no_structure", BLOCK, "The stained area has no cellular structure (a uniform colour fill)."))
    if m["eosin_share"] > EOSIN_BLOCK:
        r.append(_reason("not_ihc", BLOCK, "The stain looks like H&E (eosin pink), not a HER2 DAB immunostain."))
    elif m["eosin_share"] > EOSIN_CAUTION:
        r.append(_reason("not_ihc", CAUTION, "Unusual pink/eosin-like colour for a DAB immunostain: confirm this is a HER2 IHC section."))
    if m["foreign_fraction"] > FOREIGN_BLOCK:
        r.append(_reason("marker", BLOCK, "Much of the field carries marker, pen or annotation colour (green/blue ink)."))
    elif m["foreign_fraction"] > FOREIGN_CAUTION:
        r.append(_reason("marker", CAUTION, f"{100 * m['foreign_fraction']:.1f}% of the field carries marker or annotation colour; "
                                            "it was excluded from the measurement."))
    if m["ink_fraction"] > INK_CAUTION:
        r.append(_reason("dark_deposits", CAUTION, f"{100 * m['ink_fraction']:.1f}% of the field is near-black deposit "
                                                   "(black ink, pigment, fold or debris); it was excluded. Check that no brown "
                                                   "pigment (melanin, haemosiderin) is being read as HER2."))
    if m["dab_share"] >= NUCLEAR_PATTERN_MIN_DAB and m["nuclear_pattern"] > NUCLEAR_PATTERN_BLOCK:
        r.append(_reason("nuclear_stain", BLOCK, "The brown stain fills whole nuclei: this looks like a nuclear marker "
                                                 "(ER, PR or Ki-67), not membranous HER2."))
    elif m["dab_share"] >= NUCLEAR_PATTERN_MIN_DAB and m["nuclear_pattern"] > NUCLEAR_PATTERN_CAUTION:
        r.append(_reason("nuclear_stain", CAUTION, "Much of the brown stain sits in round, filled, nucleus-like shapes: "
                                                   "confirm this is a HER2 (membranous) stain and not ER, PR or Ki-67."))
    if tissue_percent is not None:
        if tissue_percent < TISSUE_BLOCK:
            r.append(_reason("little_tissue", BLOCK, f"Only {tissue_percent:.1f}% of the frame is tissue (at least {TISSUE_BLOCK:.0f}% is needed)."))
        elif tissue_percent < TISSUE_CAUTION:
            r.append(_reason("little_tissue", CAUTION, f"Only {tissue_percent:.1f}% of the frame is tissue."))
    if n_cells is not None and (tissue_percent is None or tissue_percent >= TISSUE_BLOCK):
        if n_cells < CELLS_BLOCK:
            r.append(_reason("few_cells", BLOCK, f"Only {n_cells} cells were measured (at least {CELLS_BLOCK} are needed for a "
                                                 "grade; ASCO/CAP percentages need many more)."))
        elif n_cells < CELLS_CAUTION:
            r.append(_reason("few_cells", CAUTION, f"Only {n_cells} cells measured: percentages are unstable; score more fields."))
    if focus is not None:
        if focus < FOCUS_FAIL:
            r.append(_reason("out_of_focus", BLOCK, "The field is out of focus: faint membranes cannot be judged. Rescan or refocus."))
        elif focus < FOCUS_WARN:
            r.append(_reason("out_of_focus", CAUTION, "Slightly soft focus: faint membranes may be under-called."))
    if edge_share is not None and edge_share > EDGE_DAB_CAUTION:
        r.append(_reason("edge_artefact", CAUTION, f"{100 * edge_share:.0f}% of the strongest staining lies at the tissue edge: "
                                                   "possible edge artefact. Score away from the edge."))
    if excluded_percent >= 0.5:
        r.append(_reason("excluded", CAUTION, f"{excluded_percent:.1f}% of the tissue was excluded as artefact before measuring."))
    if specimen and specimen.lower() not in ("breast", "breast_primary", "breast_metastasis", ""):
        r.append(_reason("not_breast", BLOCK, "Specimen is not breast: the breast ASCO/CAP rules do not apply "
                                              "(gastric cancer uses different HER2 criteria)."))
    # one entry per code, the blocking one first
    seen, out = set(), []
    for x in sorted(r, key=lambda z: z["level"] != BLOCK):
        if x["code"] not in seen:
            seen.add(x["code"])
            out.append(x)
    blocking = [x for x in out if x["level"] == BLOCK]
    return {
        "assessable": not blocking,
        "status": "not_assessable" if blocking else ("caution" if out else "ok"),
        "reasons": out,
        "summary": (blocking[0]["text"] if blocking else None),
        "metrics": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items() if k != "artefact_mask"},
    }
