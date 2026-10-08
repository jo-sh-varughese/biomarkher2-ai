"""Whole-slide HER2 analysis: tissue -> exclusions -> fields -> slide pre-score.

Pipeline (one call, ``SlideAnalyzer.run``):

1. **Overview** at ~8 um/px and a tissue mask (wsi/reader.py).
2. **Exclusions** -- blue ink / mounting-film artefacts and on-slide **control
   cores** (wsi/artefacts.py) are removed from the patient's tissue and drawn on
   the overlay, never silently dropped.
3. **Control measurement** -- the control's DAB is measured. Only when the
   laboratory has declared its control level and a reference exists is a
   per-slide DAB gain derived from it and applied to the cell evidence
   (evaluation/control_calibration.py); otherwise it is measured and reported.
4. **Fields** -- 40x fields (1024 px at 0.24 um/px, ~246 um) spread over the
   usable tissue, up to ``max_fields``. **Tumour is not segmented**: ASCO/CAP
   scores invasive tumour cells only, so the pathologist confirms that the
   fields lie in invasive tumour (the slide says so in its flags).
5. **Per field** -- cell-level membrane evidence and the pre-score model's tile
   embeddings and per-tile grades.
6. **Slide level** -- one pre-score from attention pooling over every tile
   analysed; ASCO/CAP cell percentages over all cells measured; heterogeneity
   across fields; the highest-weighted fields as hotspots for the pathologist.
7. **Safety** -- the site gate decides whether the pre-score is shown; slides
   scanned too coarsely for membrane assessment (> 0.5 um/px, i.e. below
   ~20x) get no pre-score and their cell evidence is flagged unreliable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from wsi.reader import Slide, tissue_overview_mask

OVERVIEW_MPP = 8.0
FIELD_MPP = 0.24
FIELD_PX = 1024
BLOCK_UM = 512.0                    # ink / film check is made per block of this size
BLOCK_READ_MPP = 2.0                # the check needs colour, not detail
MAX_MEMBRANE_MPP = 0.5
ARTEFACT, CONTROL = -2, -3          # region codes for excluded tissue
EXCLUDED_COLORS = {ARTEFACT: (90, 90, 90), CONTROL: (20, 150, 170)}
INK_CAST = 15.0                     # wsi/artefacts.blue_cast above this -> ink / film artefact
GRADE_RGB = {"0": (110, 130, 160), "1+": (217, 178, 48), "2+": (224, 130, 20), "3+": (200, 30, 40)}
CONTROL_CROPS = 6                   # fields read inside the control to measure its DAB


# Field-quality codes that drop a whole-slide field (the rest are judged at slide level).
FIELD_DROP_CODES = {"too_dark", "noise", "graphics", "greyscale", "no_structure", "not_ihc", "marker", "nuclear_stain"}


@dataclass
class SlideSettings:
    max_fields: int = 40
    min_tissue_fraction: float = 0.5
    max_artefact_blocks: int = 1500
    hotspots: int = 6


@dataclass
class Progress:
    stage: str = "queued"
    fraction: float = 0.0
    log: list = field(default_factory=list)

    def update(self, stage: str, fraction: float) -> None:
        self.stage, self.fraction = stage, round(float(fraction), 3)
        self.log.append(f"{time.strftime('%H:%M:%S')} {stage}")


def _uri(rgb: np.ndarray, max_side: int = 1400) -> str:
    from app.analysis import to_data_uri

    return to_data_uri(rgb, max_side=max_side)


def _rgba_uri(rgba: np.ndarray) -> str:
    import base64
    import io

    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


class SlideAnalyzer:
    def __init__(self, analyzer, settings: SlideSettings | None = None) -> None:
        """``analyzer``: app.analysis.Analyzer (pre-score engine, cell params, site policy, preprocessing).

        Optional attributes of ``analyzer`` read here: ``control_reference`` (a dict from
        configs/control_reference.json) and ``control_level`` (the control tissue's declared HER2 score, "3+").
        """
        self.analyzer = analyzer
        self.settings = settings or SlideSettings()

    # ------------------------------------------------------------------ steps
    def _artefact_map(self, slide: Slide, tissue: np.ndarray, factor: float, progress: Progress, glass):
        """Per-overview-pixel code: ARTEFACT where a block of tissue carries blue ink / film, else -1.

        The check needs only colour, so blocks are read at a coarse resolution; every block is checked (no model).
        """
        from wsi.artefacts import blue_cast

        h, w = tissue.shape
        cls = np.full((h, w), -1, dtype=np.int8)
        if slide.info.mpp is None:
            return cls
        block_l0 = BLOCK_UM / slide.info.mpp
        bo = max(1, int(round(block_l0 / factor)))
        blocks = [(r, c) for r in range(0, h, bo) for c in range(0, w, bo) if tissue[r:r + bo, c:c + bo].mean() > 0.2]
        if len(blocks) > self.settings.max_artefact_blocks:
            step = len(blocks) / self.settings.max_artefact_blocks
            blocks = [blocks[int(i * step)] for i in range(self.settings.max_artefact_blocks)]
        for i, (r, c) in enumerate(blocks):
            rgb = slide.read(int(c * factor), int(r * factor), int(block_l0), int(block_l0), target_mpp=BLOCK_READ_MPP)
            if blue_cast(rgb, glass) > INK_CAST:
                sub_h, sub_w = min(bo, h - r), min(bo, w - c)
                region = tissue[r:r + sub_h, c:c + sub_w]
                cls[r:r + sub_h, c:c + sub_w] = np.where(region, ARTEFACT, cls[r:r + sub_h, c:c + sub_w])
            if i % 25 == 0:
                progress.update(f"Checking for ink and film {i + 1}/{len(blocks)}", 0.03 + 0.12 * (i + 1) / max(1, len(blocks)))
        return cls

    def _choose_fields(self, usable, factor, slide):
        """Fields spread over the usable tissue (controls and artefacts already removed)."""
        fo = max(1, int(round(FIELD_PX * FIELD_MPP / (slide.info.mpp or FIELD_MPP) / factor)))  # field size in overview px
        h, w = usable.shape
        cands = []
        for r in range(0, h - fo + 1, fo):
            for c in range(0, w - fo + 1, fo):
                t = float(usable[r:r + fo, c:c + fo].mean())
                if t >= self.settings.min_tissue_fraction:
                    cands.append((t, r, c))
        if len(cands) > self.settings.max_fields:
            cands.sort(key=lambda t: (t[1], t[2]))
            step = len(cands) / self.settings.max_fields
            cands = [cands[int(i * step)] for i in range(self.settings.max_fields)]
        return cands, fo

    @staticmethod
    def _exclude_non_patient(tissue, cls, um_per_px):
        """Remove ink/film artefacts and on-slide control cores (wsi/artefacts.py) from the patient's tissue.

        Marks them in ``cls`` (ARTEFACT / CONTROL) so the overlay shows them, and
        returns the usable tissue mask plus what was excluded and why.
        """
        from wsi.artefacts import find_control_cores, group_pieces

        artefact = cls == ARTEFACT
        if artefact.any():  # a piece that is mostly artefact is artefact as a whole
            pieces = group_pieces(tissue, um_per_px)
            for i in np.unique(pieces[artefact]):
                piece = pieces == i
                evaluated = piece & (cls != -1)
                if i and evaluated.any() and artefact[evaluated].mean() > 0.5:
                    artefact |= piece
            cls[artefact] = ARTEFACT
        control, cores = find_control_cores(tissue & ~artefact, um_per_px)
        cls[control] = CONTROL
        flags = []
        if cores:
            flags.append(f"{len(cores)} small separate tissue core(s) look like on-slide control tissue and were "
                         "EXCLUDED from the patient's evidence (teal on the overlay). Check this is correct.")
        if artefact.any():
            flags.append(f"{float(artefact.sum()) * (um_per_px / 1000) ** 2:.1f} mm2 of blue-tinted ink / film / "
                         "mounting artefact was excluded (grey on the overlay).")
        usable = tissue & ~artefact & ~control
        return usable, {"control_cores": cores, "artefact_mm2": round(float(artefact.sum()) * (um_per_px / 1000) ** 2, 2),
                        "flags": flags}

    def _control_calibration(self, slide: Slide, cls: np.ndarray, factor: float, progress: Progress):
        """Measure the on-slide control's DAB and, only if declared and referenced, derive a per-slide DAB gain.

        Returns ``(report, gain)``; ``gain`` is None unless the correction is applied. The control tissue is
        known to be a particular HER2 level only if the laboratory says so (``analyzer.control_level``), so
        without that declaration (and a reference signature of that level) the measurement is reported, never
        used: a 0 or 1+ control read as a 3+ one would wrongly brighten the whole slide.
        """
        from scipy import ndimage

        from evaluation.control_calibration import calibration_gain, signature_from_dab
        from preprocessing.stains import deconvolve
        from preprocessing.tissue import detect_tissue

        a = self.analyzer
        reference = getattr(a, "control_reference", None)
        level = getattr(a, "control_level", None)
        mpp = slide.info.mpp
        rep = {"cores_found": 0, "measured": False, "applied": False, "gain": None, "declared_level": level,
               "reference_level": (reference or {}).get("level"), "cores": [], "reason": None}
        control = cls == CONTROL
        if not control.any():
            rep["reason"] = "No on-slide control tissue was found on this slide."
            return rep, None
        if mpp is None or mpp > MAX_MEMBRANE_MPP:
            rep["reason"] = "The slide is not scanned finely enough (at least ~20x, 0.5 um/px) to measure the control's DAB."
            return rep, None
        labels, n = ndimage.label(control)
        rep["cores_found"] = int(n)
        fo = max(1, int(round(FIELD_PX * FIELD_MPP / mpp / factor)))
        thr = a.preprocessing.stain.thresholds()[0]
        sigs = []
        for k in range(1, n + 1):
            core = labels == k
            ys, xs = np.nonzero(core)
            wins = []
            for r in range(max(0, ys.min() - fo // 2), ys.max() + 1, max(1, fo // 2)):
                for c in range(max(0, xs.min() - fo // 2), xs.max() + 1, max(1, fo // 2)):
                    if core[r:r + fo, c:c + fo].mean() >= 0.5:
                        wins.append((r, c))
            if not wins:   # a core smaller than half a field: one field centred on it
                wins = [(max(0, int(ys.mean()) - fo // 2), max(0, int(xs.mean()) - fo // 2))]
            step = max(1, len(wins) // CONTROL_CROPS)
            values = []
            for r, c in wins[::step][:CONTROL_CROPS]:
                size_l0 = int(FIELD_PX * FIELD_MPP / mpp)
                rgb = slide.read(int(c * factor), int(r * factor), size_l0, size_l0, target_mpp=FIELD_MPP)
                tis = detect_tissue(rgb, a.preprocessing.tissue)
                dab = deconvolve(rgb)[..., 1][tis]
                values.append(dab[dab >= thr])
            vals = np.concatenate(values) if values else np.zeros(0)
            try:
                sig = signature_from_dab(vals)
            except ValueError as exc:
                rep["cores"].append({"index": k, "error": str(exc)})
                continue
            rep["cores"].append({"index": k, "area_mm2": round(float(core.sum()) * (factor * mpp / 1000) ** 2, 2),
                                 **{p: round(v, 4) for p, v in sig.items() if p != "stained_pixels"},
                                 "stained_pixels": sig["stained_pixels"]})
            sigs.append(sig)
        progress.update("Measured on-slide control", 0.18)
        if not sigs:
            rep["reason"] = "The control tissue has too little DAB to measure (a failed or negative control?)."
            return rep, None
        rep["measured"] = True
        strongest = max(sigs, key=lambda s: s["p90"])
        rep["strongest_p90"] = round(strongest["p90"], 4)
        if reference is None or level is None:
            rep["reason"] = ("Measured and reported only. To correct the slide's DAB from its control, declare the control's "
                             "HER2 level (--control-level 3+) and provide a reference signature "
                             "(configs/control_reference.json, scripts/build_control_reference.py).")
            return rep, None
        if level != reference.get("level") or level != "3+":
            rep["reason"] = f"Only a declared 3+ control with a 3+ reference is supported (declared {level}, reference {reference.get('level')})."
            return rep, None
        try:
            gain = calibration_gain(strongest, reference)
        except ValueError as exc:
            rep["reason"] = str(exc)
            return rep, None
        rep.update(applied=True, gain=round(gain, 3), reference_p90=reference.get("p90"),
                   reason=f"DAB of this slide's cell evidence rescaled x{gain:.2f} from the strongest control core (declared {level}).")
        return rep, gain

    # -------------------------------------------------------------------- run
    def run(self, slide: Slide, progress: Progress | None = None) -> dict:
        from app.cells import analyze_cells, overlay_cells, public_cells, summarize
        from app.guidance import recommend
        from app.prescore import embed_field, pool_slide
        from evaluation.control_calibration import apply_dab_gain
        from preprocessing.tissue import detect_tissue

        progress = progress or Progress()
        a = self.analyzer
        policy = dict(a.site_policy)
        mpp = slide.info.mpp
        started = time.time()
        progress.update("Reading slide overview", 0.02)
        overview, factor = slide.overview(OVERVIEW_MPP)
        from app.learning.store import case_id_for

        slide_case_id = case_id_for(overview)  # links a slide review to this slide's stored features
        tissue = tissue_overview_mask(overview)
        glass = np.median(overview[~tissue].reshape(-1, 3), axis=0) if (~tissue).any() else np.array([235, 235, 235])
        cls = self._artefact_map(slide, tissue, factor, progress, glass)
        usable, excluded = self._exclude_non_patient(tissue, cls, factor * (mpp or FIELD_MPP))
        control_report, gain = self._control_calibration(slide, cls, factor, progress)
        fields, fo = self._choose_fields(usable, factor, slide)
        flags = list(excluded["flags"])
        if mpp is None:
            flags.append("Scanner microns-per-pixel unknown: magnification cannot be confirmed.")
        too_coarse = mpp is not None and mpp > MAX_MEMBRANE_MPP
        if too_coarse:
            flags.append(f"Scanned at {mpp:.2f} um/px (below ~20x): membrane completeness cannot be judged reliably; "
                         "the AI pre-score is withheld and cell evidence is indicative only.")
        flags.append("Tumour is not segmented: fields are spread over all usable tissue, so stroma, in-situ carcinoma and "
                     "normal ducts are included. ASCO/CAP scores invasive tumour only: check that each field lies in it.")
        if control_report["cores_found"]:
            if control_report["applied"]:
                flags.append(f"On-slide control used for stain calibration: {control_report['reason']}")
            elif control_report["measured"]:
                flags.append(f"On-slide control measured, not applied: {control_report['reason']}")
            else:
                flags.append(f"On-slide control could not be measured: {control_report['reason']}")

        from app.decision import FOCUS_FAIL, focus_score
        from app.field_quality import assess, measure_image

        embeddings, records, field_results, rejected_fields = [], [], [], []
        engine = a.prescore_engine
        for i, (score, r, c) in enumerate(fields):
            x0, y0 = int(c * factor), int(r * factor)
            size_l0 = int(FIELD_PX * FIELD_MPP / (mpp or FIELD_MPP))
            rgb = slide.read(x0, y0, size_l0, size_l0, target_mpp=FIELD_MPP if mpp else None)
            rgb = np.asarray(Image.fromarray(rgb).resize((FIELD_PX, FIELD_PX))) if rgb.shape[0] != FIELD_PX else rgb
            # Field-quality gate (app/field_quality.py): a field that is not a
            # usable HER2 IHC field (wrong stain, marker, graphics, out of focus)
            # contributes nothing; marker colour, black ink and deposits are cut
            # out of the tissue of the fields that are kept.
            fq = measure_image(rgb)
            verdict = assess(fq, focus=None)
            bad = [x for x in verdict["reasons"] if x["level"] == "block" and x["code"] in FIELD_DROP_CODES]
            if bad:
                rejected_fields.append({"index": i, "x": x0, "y": y0, "size": size_l0, "code": bad[0]["code"],
                                        "reason": bad[0]["text"]})
                progress.update(f"Analysing field {i + 1}/{len(fields)}", 0.2 + 0.75 * (i + 1) / max(1, len(fields)))
                continue
            analysed = detect_tissue(rgb, a.preprocessing.tissue) & ~ndimage.binary_dilation(fq["artefact_mask"], iterations=3)
            # On a slide scanned below ~20x the field is upsampled, so it always looks
            # soft; the magnification rule already withholds the grade there.
            fq_focus = None if too_coarse else focus_score(rgb, analysed)
            if fq_focus is not None and fq_focus < FOCUS_FAIL:
                rejected_fields.append({"index": i, "x": x0, "y": y0, "size": size_l0, "code": "out_of_focus",
                                        "reason": "Field out of focus."})
                continue
            # the neural model sees the field as scanned (it is trained with stain augmentation); only the
            # threshold-based cell evidence is rescaled by the control's gain
            cell = analyze_cells(apply_dab_gain(rgb, gain) if gain else rgb, analysed, a.preprocessing.stain.thresholds(), a.cell_params)
            records += cell["cells"]
            entry = {"index": i, "x": x0, "y": y0, "size": size_l0, "overview_box": [int(r), int(c), int(fo)],
                     "tissue_fraction": round(float(score), 3), "cells": cell["summary"]["cells_measured"],
                     "cell_category": cell["summary"]["field_category"]}
            if engine is not None and not too_coarse:
                emb, tile_probs = embed_field(engine, rgb)
                embeddings.append(emb)
                mean_probs = tile_probs.mean(0)
                entry["prescore_probabilities"] = {g: round(float(p), 3) for g, p in zip(("0", "1+", "2+", "3+"), mean_probs)}
                entry["prescore_category"] = ("0", "1+", "2+", "3+")[int(mean_probs.argmax())]
                entry["_tiles"] = emb.shape[0]
            entry["_rgb"] = rgb
            entry["_cells"] = cell
            field_results.append(entry)
            progress.update(f"Analysing field {i + 1}/{len(fields)}", 0.2 + 0.75 * (i + 1) / max(1, len(fields)))

        # ---- slide level: is the slide itself scorable?
        n_sel = len(fields)
        slide_block = None
        codes = [f["code"] for f in rejected_fields]
        if n_sel and codes.count("not_ihc") > n_sel / 2:
            slide_block = "This slide looks like H&E (eosin pink), not a HER2 DAB immunostain."
        elif n_sel and codes.count("nuclear_stain") > n_sel / 2:
            slide_block = "The brown stain fills whole nuclei: this looks like a nuclear marker (ER, PR or Ki-67), not HER2."
        elif not field_results:
            slide_block = "No usable field could be measured on this slide (see the rejected fields)."
        if rejected_fields:
            flags.append(f"{len(rejected_fields)} of {n_sel} fields were rejected by the field-quality check "
                         f"({', '.join(sorted(set(c.replace('_', ' ') for c in codes)))}).")
        if slide_block:
            flags.insert(0, slide_block)
        cells_summary = summarize(records, a.cell_params)
        cells_summary["fields_measured"] = len(field_results)
        cells_summary["caveat"] = ("Cells are counted over the usable tissue of the selected fields (on-slide controls and "
                                   "artefacts excluded). Tumour is not segmented, so stroma, in-situ carcinoma and normal "
                                   "ducts are included, and membrane completeness and intensity cut points are provisional. "
                                   "Read the percentages as measured evidence, not as the invasive-tumour percentage.")
        if too_coarse:
            cells_summary["flags"] = cells_summary.get("flags", []) + ["Indicative only: scanned below ~20x."]
        prescore_public, block = None, None
        if engine is not None:
            block = {"available": True, "site": policy.get("site"), "gate_status": policy.get("status"),
                     "validated": bool(policy.get("show_scores")), "requires_pathologist_confirmation": True}
            if embeddings and not too_coarse:
                import torch

                all_emb = torch.cat(embeddings)
                prescore_public, attention = pool_slide(engine, all_emb)
                learning = getattr(a, "learning", None)
                if learning is not None:
                    from app.prescore import TILE

                    learning.record(slide_case_id, all_emb.numpy(), kind="slide", grid=(int(all_emb.shape[0]), 1),
                                    tile_px=TILE, summary={"prescore": prescore_public["category"],
                                                           "slide": Path(str(slide.info.path)).name})
                offsets = np.cumsum([0] + [f.get("_tiles", 0) for f in field_results])
                for f, a0, a1 in zip(field_results, offsets[:-1], offsets[1:]):
                    f["attention"] = round(float(attention[a0:a1].sum()), 4)
                grades = [f["prescore_category"] for f in field_results if "prescore_category" in f]
                share = {g: round(grades.count(g) / len(grades), 3) for g in ("0", "1+", "2+", "3+")} if grades else {}
                spread = (max(("0", "1+", "2+", "3+").index(g) for g in grades) - min(("0", "1+", "2+", "3+").index(g) for g in grades)) if grades else 0
                prescore_public["heterogeneity"] = {"fields_by_grade": share, "regions_by_grade": share, "grade_spread": int(spread),
                                                    "heterogeneous": bool(spread >= 2 and len(grades) >= 2)}
                prescore_public["regions"] = []
                show = (bool(policy.get("show_scores")) or bool(policy.get("research_mode"))) and not too_coarse and not slide_block
                block["shown"] = show
                if show:
                    block["prescore"] = prescore_public
                    if not policy.get("show_scores"):
                        block["warning"] = "RESEARCH MODE: this site is not locally validated; this pre-score must not inform patient care."
                else:
                    block["withheld_reasons"] = list(policy.get("reasons") or [])
            else:
                block["shown"] = False
                block["withheld_reasons"] = flags[:1] or ["No analysable fields."]
        from app.decision import decision_support
        from app.explain import build_explanation

        shown_prescore = prescore_public if block and block.get("shown") else None
        thresholds = a.preprocessing.stain.thresholds()
        decision = decision_support(None, None, records, cells_summary, a.cell_params, thresholds, shown_prescore,
                                    block, scan_mpp_ok=not too_coarse)
        slide_quality = None
        wrong_stain = bool(slide_block) and ("H&E" in slide_block or "nuclear marker" in slide_block)
        if slide_block:
            slide_quality = {"assessable": False, "status": "not_assessable", "summary": slide_block,
                             "reasons": [{"code": (codes and max(set(codes), key=codes.count)) or "few_cells",
                                          "level": "block", "text": slide_block}]}
            cells_summary["measured_category"] = cells_summary.get("field_category")
            cells_summary["field_category"] = None
        guidance = recommend(shown_prescore, cells_summary, policy, extra_flags=flags,
                             assessable=not too_coarse, near_2plus=decision["near_2plus"],
                             # a wrong stain outranks magnification; otherwise "rescan at 20x" governs
                             quality=slide_quality if (slide_quality and (not too_coarse or wrong_stain)) else None)
        cells_summary["decision_support"] = decision
        cells_summary["explanation"] = build_explanation(None, {"cells": records}, cells_summary, shown_prescore, block,
                                                         guidance, a.cell_params, thresholds)

        # ---- images
        progress.update("Rendering overlays", 0.97)
        excluded_rgba = np.zeros(overview.shape[:2] + (4,), dtype=np.uint8)
        for k, col in EXCLUDED_COLORS.items():
            sel = cls == k
            excluded_rgba[sel, :3] = col
            excluded_rgba[sel, 3] = 140
        grade_rgba = np.zeros_like(excluded_rgba)
        for f in field_results:
            r, c, s = f["overview_box"]
            g = f.get("prescore_category") or f["cell_category"]
            grade_rgba[r:r + s, c:c + s, :3] = GRADE_RGB[g]
            grade_rgba[r:r + s, c:c + s, 3] = 150
            grade_rgba[r:r + s, c:c + max(1, s // 10), 3] = 255
            grade_rgba[r:r + s, c + s - max(1, s // 10):c + s, 3] = 255
        ranked = sorted(field_results, key=lambda f: -(f.get("attention") or f["tissue_fraction"]))[: self.settings.hotspots]
        hotspots = [{"index": f["index"], "x": f["x"], "y": f["y"], "size": f["size"],
                     "prescore_category": f.get("prescore_category"), "cell_category": f["cell_category"],
                     "attention": f.get("attention"), "cells": f["cells"],
                     "image": _uri(f["_rgb"], 420), "cells_image": _uri(overlay_cells(f["_rgb"], f["_cells"]), 420)} for f in ranked]
        # ISH targets on a slide: the highest-grade hotspot fields
        decision["ish_targets"] = [
            {"row": h["index"] + 1, "col": 0, "grade": h.get("prescore_category") or h["cell_category"],
             "weight": round(100 * (h.get("attention") or 0)), "image": h["image"], "field": h["index"] + 1}
            for h in hotspots if (h.get("prescore_category") or h["cell_category"]) in ("2+", "3+")][:3]
        fields_public = [{k: v for k, v in f.items() if not k.startswith("_")} for f in field_results]
        tissue_area_mm2 = float(usable.sum()) * (factor * (mpp or 0.25) / 1000) ** 2
        return {
            "slide": slide.info.to_dict() | {"overview_um_per_px": round(factor * (mpp or 0), 3)},
            "case_id": slide_case_id,
            "ai_prescore": block,
            "cell_evidence": cells_summary | {"cells": public_cells(records)[:3000]},
            "guidance": guidance,
            "fields": fields_public,
            "rejected_fields": rejected_fields,
            "quality": slide_quality or {"assessable": True, "status": "ok", "reasons": [], "summary": None},
            "hotspots": hotspots,
            "tissue": {"usable_area_mm2": round(tissue_area_mm2, 2), "fields_selected": len(field_results),
                       "tumour_segmented": False},
            "stain_control": control_report,
            "flags": flags,
            "excluded": {k: v for k, v in excluded.items() if k != "flags"},
            "images": {"overview": _uri(overview), "excluded_overlay": _rgba_uri(excluded_rgba), "grade_overlay": _rgba_uri(grade_rgba)},
            "overview_size": [int(overview.shape[1]), int(overview.shape[0])],
            "minutes": round((time.time() - started) / 60, 2),
            "caveats": {"slide": "Whole-slide pre-scoring aid. Fields are a sample of the tissue, not segmented invasive tumour; "
                                 "the pathologist reviews the slide and confirms the score and any ISH decision.",
                        "cells": cells_summary.get("caveat", ""), "guidance": guidance.get("caveat", "")},
        }
