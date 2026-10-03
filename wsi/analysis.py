"""Whole-slide HER2 analysis: tissue -> invasive tumour -> fields -> slide pre-score.

Pipeline (one call, ``SlideAnalyzer.run``):

1. **Overview** at ~8 um/px and a tissue mask (wsi/reader.py).
2. **Tumour map** -- the haematoxylin-channel segmenter (wsi/tumour.py) over
   tissue blocks of 512 um at 0.5 um/px. If a slide has more blocks than
   ``max_tumour_blocks`` (CPU), a regular grid sample is taken and the rest is
   marked "not evaluated" -- never silently treated as tumour-free.
3. **Fields** -- 40x fields (1024 px at 0.24 um/px, ~246 um) centred on
   invasive-tumour blocks, up to ``max_fields``, spread across the tumour.
4. **Per field** -- cell-level membrane evidence restricted to invasive-tumour
   pixels (ASCO/CAP counts invasive tumour cells only), and the pre-score
   model's tile embeddings and per-tile grades.
5. **Slide level** -- one pre-score from attention pooling over every tumour
   tile analysed; ASCO/CAP cell percentages over all invasive tumour cells
   measured; heterogeneity across fields; the highest-weighted fields as
   hotspots for the pathologist to check.
6. **Safety** -- the site gate decides whether the pre-score is shown; slides
   scanned too coarsely for membrane assessment (> 0.5 um/px, i.e. below
   ~20x) get no pre-score and their cell evidence is flagged unreliable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from wsi.reader import Slide, tissue_overview_mask

OVERVIEW_MPP = 8.0
FIELD_MPP = 0.24
FIELD_PX = 1024
TUMOUR_BLOCK_UM = 512.0
MAX_MEMBRANE_MPP = 0.5
TUMOUR_COLORS = {1: (210, 40, 60), 2: (150, 60, 200), 3: (40, 160, 90)}
ARTEFACT, CONTROL = -2, -3          # tumour-map codes for excluded regions
EXCLUDED_COLORS = {ARTEFACT: (90, 90, 90), CONTROL: (20, 150, 170)}
INK_CAST = 15.0                     # wsi/artefacts.blue_cast above this -> ink / film artefact
GRADE_RGB = {"0": (110, 130, 160), "1+": (217, 178, 48), "2+": (224, 130, 20), "3+": (200, 30, 40)}


@dataclass
class SlideSettings:
    max_tumour_blocks: int = 400
    max_fields: int = 40
    min_invasive_fraction: float = 0.3
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
    def __init__(self, analyzer, tumour_model=None, settings: SlideSettings | None = None) -> None:
        """``analyzer``: app.analysis.Analyzer (pre-score engine, cell params, site policy, preprocessing)."""
        self.analyzer = analyzer
        self.tumour = tumour_model
        self.settings = settings or SlideSettings()

    # ------------------------------------------------------------------ steps
    def _tumour_map(self, slide: Slide, tissue: np.ndarray, factor: float, progress: Progress, glass=(235, 235, 235)):
        """Per-overview-pixel class (-1 not evaluated, -2 ink/film artefact, 0 other, 1 invasive, 2 in-situ,
        3 glands) + invasive prob."""
        from wsi.artefacts import blue_cast

        h, w = tissue.shape
        cls = np.full((h, w), -1, dtype=np.int8)
        inv = np.zeros((h, w), dtype=np.float32)
        if self.tumour is None or slide.info.mpp is None:
            return cls, inv, {"evaluated_blocks": 0, "total_blocks": 0, "note": "No tumour model: all tissue is analysed."}
        block_l0 = TUMOUR_BLOCK_UM / slide.info.mpp
        bo = max(1, int(round(block_l0 / factor)))  # block size in overview px
        blocks = [(r, c) for r in range(0, h, bo) for c in range(0, w, bo) if tissue[r:r + bo, c:c + bo].mean() > 0.2]
        total = len(blocks)
        if total > self.settings.max_tumour_blocks:
            step = total / self.settings.max_tumour_blocks
            blocks = [blocks[int(i * step)] for i in range(self.settings.max_tumour_blocks)]
        for i, (r, c) in enumerate(blocks):
            x0, y0 = int(c * factor), int(r * factor)
            rgb = slide.read(x0, y0, int(block_l0), int(block_l0), target_mpp=0.5)
            sub_h, sub_w = min(bo, h - r), min(bo, w - c)
            region = tissue[r:r + sub_h, c:c + sub_w]
            if blue_cast(rgb, glass) > INK_CAST:
                cls[r:r + sub_h, c:c + sub_w] = np.where(region, ARTEFACT, cls[r:r + sub_h, c:c + sub_w])
                progress.update(f"Tumour detection {i + 1}/{len(blocks)}", 0.05 + 0.45 * (i + 1) / max(1, len(blocks)))
                continue
            probs = self.tumour.predict(rgb, "ihc")
            small = np.asarray(Image.fromarray((probs[..., 1] * 255).astype(np.uint8)).resize((sub_w, sub_h), Image.BILINEAR)) / 255.0
            lab = np.asarray(Image.fromarray(probs.argmax(-1).astype(np.uint8)).resize((sub_w, sub_h), Image.NEAREST))
            inv[r:r + sub_h, c:c + sub_w] = np.where(region, small, 0)
            cls[r:r + sub_h, c:c + sub_w] = np.where(region, lab, cls[r:r + sub_h, c:c + sub_w])
            progress.update(f"Tumour detection {i + 1}/{len(blocks)}", 0.05 + 0.45 * (i + 1) / max(1, len(blocks)))
        note = None if len(blocks) == total else f"Tumour map sampled: {len(blocks)} of {total} tissue blocks evaluated (CPU limit)."
        return cls, inv, {"evaluated_blocks": len(blocks), "total_blocks": total, "note": note}

    def _choose_fields(self, tissue, cls, inv, factor, slide):
        """``tissue`` here is the usable tissue: controls and artefacts already removed."""
        fo = max(1, int(round(FIELD_PX * FIELD_MPP / (slide.info.mpp or FIELD_MPP) / factor)))  # field size in overview px
        h, w = tissue.shape
        has_tumour_model = (cls >= 0).any()
        cands = []
        for r in range(0, h - fo + 1, fo):
            for c in range(0, w - fo + 1, fo):
                t = tissue[r:r + fo, c:c + fo].mean()
                if t < 0.5:
                    continue
                score = float((cls[r:r + fo, c:c + fo] == 1).mean()) if has_tumour_model else t
                if has_tumour_model and score < self.settings.min_invasive_fraction:
                    continue
                cands.append((score, r, c))
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
                         "EXCLUDED from the patient's evidence (teal on the tumour map). Check this is correct.")
        if artefact.any():
            flags.append(f"{float(artefact.sum()) * (um_per_px / 1000) ** 2:.1f} mm2 of blue-tinted ink / film / "
                         "mounting artefact was excluded (grey on the tumour map).")
        usable = tissue & ~artefact & ~control
        return usable, {"control_cores": cores, "artefact_mm2": round(float(artefact.sum()) * (um_per_px / 1000) ** 2, 2),
                        "flags": flags}

    # -------------------------------------------------------------------- run
    def run(self, slide: Slide, progress: Progress | None = None) -> dict:
        from app.cells import analyze_cells, overlay_cells, public_cells, summarize
        from app.guidance import recommend
        from app.prescore import embed_field, pool_slide
        from preprocessing.tissue import detect_tissue

        progress = progress or Progress()
        a = self.analyzer
        policy = dict(a.site_policy)
        mpp = slide.info.mpp
        started = time.time()
        progress.update("Reading slide overview", 0.02)
        overview, factor = slide.overview(OVERVIEW_MPP)
        tissue = tissue_overview_mask(overview)
        glass = np.median(overview[~tissue].reshape(-1, 3), axis=0) if (~tissue).any() else np.array([235, 235, 235])
        cls, inv, tumour_stats = self._tumour_map(slide, tissue, factor, progress, glass)
        usable, excluded = self._exclude_non_patient(tissue, cls, factor * (mpp or FIELD_MPP))
        inv = np.where(usable, inv, 0)
        fields, fo = self._choose_fields(usable, cls, inv, factor, slide)
        flags = list(excluded["flags"])
        if mpp is None:
            flags.append("Scanner microns-per-pixel unknown: magnification cannot be confirmed.")
        too_coarse = mpp is not None and mpp > MAX_MEMBRANE_MPP
        if too_coarse:
            flags.append(f"Scanned at {mpp:.2f} um/px (below ~20x): membrane completeness cannot be judged reliably; "
                         "the AI pre-score is withheld and cell evidence is indicative only.")
        if tumour_stats.get("note"):
            flags.append(tumour_stats["note"])
        if not (cls >= 0).any():
            flags.append("Invasive tumour was not segmented: every tissue field counts, including stroma and normal ducts.")

        embeddings, records, field_results = [], [], []
        engine = a.prescore_engine
        for i, (score, r, c) in enumerate(fields):
            x0, y0 = int(c * factor), int(r * factor)
            size_l0 = int(FIELD_PX * FIELD_MPP / (mpp or FIELD_MPP))
            rgb = slide.read(x0, y0, size_l0, size_l0, target_mpp=FIELD_MPP if mpp else None)
            rgb = np.asarray(Image.fromarray(rgb).resize((FIELD_PX, FIELD_PX))) if rgb.shape[0] != FIELD_PX else rgb
            tis = detect_tissue(rgb, a.preprocessing.tissue)
            region_cls = cls[r:r + fo, c:c + fo]
            if (region_cls >= 0).any():
                tum = np.asarray(Image.fromarray((region_cls == 1).astype(np.uint8) * 255).resize((FIELD_PX, FIELD_PX), Image.NEAREST)) > 0
                analysed = tis & tum
            else:
                analysed = tis
            cell = analyze_cells(rgb, analysed, a.preprocessing.stain.thresholds(), a.cell_params)
            records += cell["cells"]
            entry = {"index": i, "x": x0, "y": y0, "size": size_l0, "overview_box": [int(r), int(c), int(fo)],
                     "invasive_fraction": round(float(score), 3), "cells": cell["summary"]["cells_measured"],
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
            progress.update(f"Analysing field {i + 1}/{len(fields)}", 0.5 + 0.45 * (i + 1) / max(1, len(fields)))

        # ---- slide level
        cells_summary = summarize(records, a.cell_params)
        cells_summary["fields_measured"] = len(field_results)
        if (cls == 1).any():
            cells_summary["caveat"] = ("Cells are counted only inside regions the tumour model marked as invasive "
                                       "tumour (on-slide controls and artefacts excluded). The tumour map is a model "
                                       "output that the pathologist checks; membrane completeness and intensity cut "
                                       "points are provisional. Read the percentages as measured evidence.")
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
                offsets = np.cumsum([0] + [f.get("_tiles", 0) for f in field_results])
                for f, a0, a1 in zip(field_results, offsets[:-1], offsets[1:]):
                    f["attention"] = round(float(attention[a0:a1].sum()), 4)
                grades = [f["prescore_category"] for f in field_results if "prescore_category" in f]
                share = {g: round(grades.count(g) / len(grades), 3) for g in ("0", "1+", "2+", "3+")} if grades else {}
                spread = (max(("0", "1+", "2+", "3+").index(g) for g in grades) - min(("0", "1+", "2+", "3+").index(g) for g in grades)) if grades else 0
                prescore_public["heterogeneity"] = {"fields_by_grade": share, "regions_by_grade": share, "grade_spread": int(spread),
                                                    "heterogeneous": bool(spread >= 2 and len(grades) >= 2)}
                prescore_public["regions"] = []
                show = (bool(policy.get("show_scores")) or bool(policy.get("research_mode"))) and not too_coarse
                block["shown"] = show
                if show:
                    block["prescore"] = prescore_public
                    if not policy.get("show_scores"):
                        block["warning"] = "RESEARCH MODE: this site is not locally validated; this pre-score must not inform patient care."
                else:
                    block["withheld_reasons"] = list(policy.get("reasons") or [])
            else:
                block["shown"] = False
                block["withheld_reasons"] = flags[:1] or ["No analysable tumour fields."]
        from app.decision import decision_support
        from app.explain import build_explanation

        shown_prescore = prescore_public if block and block.get("shown") else None
        thresholds = a.preprocessing.stain.thresholds()
        decision = decision_support(None, None, records, cells_summary, a.cell_params, thresholds, shown_prescore,
                                    block, scan_mpp_ok=not too_coarse)
        guidance = recommend(shown_prescore, cells_summary, policy, extra_flags=flags,
                             assessable=not too_coarse, near_2plus=decision["near_2plus"])
        cells_summary["decision_support"] = decision
        cells_summary["explanation"] = build_explanation(None, {"cells": records}, cells_summary, shown_prescore, block,
                                                         guidance, a.cell_params, thresholds)

        # ---- images
        progress.update("Rendering overlays", 0.97)
        tumour_rgba = np.zeros(overview.shape[:2] + (4,), dtype=np.uint8)
        for k, col in TUMOUR_COLORS.items():
            sel = cls == k
            tumour_rgba[sel, :3] = col
            tumour_rgba[sel, 3] = 110 if k == 1 else 90
        for k, col in EXCLUDED_COLORS.items():
            sel = cls == k
            tumour_rgba[sel, :3] = col
            tumour_rgba[sel, 3] = 140
        grade_rgba = np.zeros_like(tumour_rgba)
        for f in field_results:
            r, c, s = f["overview_box"]
            g = f.get("prescore_category") or f["cell_category"]
            grade_rgba[r:r + s, c:c + s, :3] = GRADE_RGB[g]
            grade_rgba[r:r + s, c:c + s, 3] = 150
            grade_rgba[r:r + s, c:c + max(1, s // 10), 3] = 255
            grade_rgba[r:r + s, c + s - max(1, s // 10):c + s, 3] = 255
        ranked = sorted(field_results, key=lambda f: -(f.get("attention") or f["invasive_fraction"]))[: self.settings.hotspots]
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
        tumour_area_mm2 = float((cls == 1).sum()) * (factor * (mpp or 0.25) / 1000) ** 2
        return {
            "slide": slide.info.to_dict() | {"overview_um_per_px": round(factor * (mpp or 0), 3)},
            "ai_prescore": block,
            "cell_evidence": cells_summary | {"cells": public_cells(records)[:3000]},
            "guidance": guidance,
            "fields": fields_public,
            "hotspots": hotspots,
            "tumour": tumour_stats | {"invasive_area_mm2": round(tumour_area_mm2, 2), "model": getattr(self.tumour, "info", None)},
            "flags": flags,
            "excluded": {k: v for k, v in excluded.items() if k != "flags"},
            "images": {"overview": _uri(overview), "tumour_overlay": _rgba_uri(tumour_rgba), "grade_overlay": _rgba_uri(grade_rgba)},
            "overview_size": [int(overview.shape[1]), int(overview.shape[0])],
            "minutes": round((time.time() - started) / 60, 2),
            "caveats": {"slide": "Whole-slide pre-scoring aid. Fields are a sample of the invasive tumour; the pathologist "
                                 "reviews the slide and confirms the score and any ISH decision.",
                        "cells": cells_summary.get("caveat", ""), "guidance": guidance.get("caveat", "")},
        }
