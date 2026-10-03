"""Plain-language explanation of one field's result, for the pathologist.

Everything here is derived from numbers the analysis already measured -- the
AI pre-score and its regions, the per-cell membrane measurements, the ASCO/CAP
rule the cell counts satisfy -- and says them in the order a pathologist
reasons: what the AI looked at and concluded, what the cells show, which rule
that meets, whether the two agree, how sure the system is, and what could
change the answer. Nothing is invented: a sentence is produced only when the
number behind it exists.

Also returned: an ASCO/CAP criteria check (each grade's definition, the
measured share, met or not), real example cells for each category with the
membrane ring that was measured drawn on them, and the distributions of
membrane completeness and intensity behind the counts.
"""

from __future__ import annotations

import numpy as np

GRADES = ("0", "1+", "2+", "3+")
CELL_RGB = {"0": (110, 130, 160), "1+": (217, 178, 48), "2+": (224, 130, 20), "3+": (200, 30, 40)}


def _pct(v: float) -> str:
    return f"{v:.1f}%"


def _crop_examples(rgb: np.ndarray, cells: dict, per_category: int = 4, size: int = 120) -> dict:
    """Up to ``per_category`` example cells per category, each a JPEG data URI
    with that cell's measured membrane ring drawn in its category colour.

    Examples are spread across the category's range of membrane intensity
    (not just the most typical cells), so the gallery shows the spread the
    count hides.
    """
    from app.analysis import to_data_uri

    labels, ring = cells.get("labels"), cells.get("ring")
    records = cells.get("cells") or []
    if rgb is None or labels is None or ring is None or not records:
        return {g: [] for g in GRADES}
    h, w = labels.shape
    half = size // 2
    out: dict[str, list] = {}
    for g in GRADES:
        pool = sorted((r for r in records if r["category"] == g), key=lambda r: r.get("membrane_od", 0))
        if not pool:
            out[g] = []
            continue
        idx = np.unique(np.linspace(0, len(pool) - 1, min(per_category, len(pool))).round().astype(int))
        examples = []
        for i in idx:
            r = pool[int(i)]
            cy, cx = int(round(r["y"])), int(round(r["x"]))
            y0, x0 = max(0, cy - half), max(0, cx - half)
            y1, x1 = min(h, y0 + size), min(w, x0 + size)
            y0, x0 = max(0, y1 - size), max(0, x1 - size)
            crop = rgb[y0:y1, x0:x1].astype(np.float32).copy()
            mine = (labels[y0:y1, x0:x1] == r["id"]) & ring[y0:y1, x0:x1]
            crop[mine] = crop[mine] * 0.25 + np.array(CELL_RGB[g], dtype=np.float32) * 0.75
            examples.append({
                "image": to_data_uri(np.clip(crop, 0, 255).astype(np.uint8), max_side=size),
                "completeness": round(float(r.get("completeness", 0.0)) * 100),
                "membrane_od": r.get("membrane_od"),
                "level": r.get("level"),
                "atypical": bool(r.get("atypical")),
            })
        out[g] = examples
    return out


def _distributions(records: list[dict]) -> dict:
    comp = np.array([r.get("completeness", 0.0) for r in records], dtype=float)
    bins = [0, 0.15, 0.5, 0.75, 1.0001]
    names = ["< 15% of the circumference", "15-50%", "50-75%", "≥ 75% (complete)"]
    counts = np.histogram(comp, bins=bins)[0] if comp.size else np.zeros(4, int)
    levels = {lv: sum(r.get("level") == lv for r in records) for lv in ("none", "weak", "moderate", "strong")}
    return {"completeness": [{"label": n, "count": int(c)} for n, c in zip(names, counts)],
            "intensity": [{"label": k, "count": int(v)} for k, v in levels.items()]}


def build_explanation(rgb: np.ndarray, cells: dict, summary: dict, prescore: dict | None, block: dict | None,
                      guidance: dict, params, thresholds: tuple[float, float, float]) -> dict:
    """The explanation payload for one field (see module docstring)."""
    pct = summary.get("percent") or {}
    n = int(summary.get("cells_measured") or 0)
    rule = float(getattr(params, "rule_percent", 10.0))
    faint = params.membrane_faint if params.membrane_faint is not None else thresholds[0]
    strong = params.membrane_strong if params.membrane_strong is not None else thresholds[2]
    at1, at2 = float(summary.get("percent_at_least_1plus") or 0), float(summary.get("percent_at_least_2plus") or 0)
    records = cells.get("cells") or []

    steps: list[dict] = []
    # 1 -- what the AI looked at and concluded
    if prescore and not (prescore.get("regions") or []) and (prescore.get("heterogeneity") or {}).get("fields_by_grade"):
        share = prescore["heterogeneity"]["fields_by_grade"]
        steps.append({"title": "What the AI looked at", "text": (
            "The AI graded every analysed tumour field and pooled them with attention weights: "
            + ", ".join(f"{round(v * 100)}% of fields {g}" for g, v in share.items() if v)
            + f". Pooled across the slide, it suggests IHC {prescore['category']} with "
              f"{round(prescore['confidence'] * 100)}% probability. The hotspot fields are the ones it weighed most.")})
    elif prescore:
        regions = prescore.get("regions") or []
        by_grade = {g: sum(1 for r in regions if r.get("category") == g) for g in GRADES}
        top = max(regions, key=lambda r: r.get("attention") or 0) if regions else None
        text = (f"The AI split the field into {len(regions)} region(s) and graded each one: "
                + ", ".join(f"{v} × {g}" for g, v in by_grade.items() if v) + ". ")
        if top:
            text += (f"The region it weighed most (row {top['row'] + 1}, column {top['col'] + 1}, "
                     f"{round((top.get('attention') or 0) * 100)}% of the weight) looks {top['category']}. ")
        text += (f"Pooling all regions, it suggests IHC {prescore['category']} "
                 f"with {round(prescore['confidence'] * 100)}% probability.")
        steps.append({"title": "What the AI looked at", "text": text})
    elif block and block.get("available") and not block.get("shown"):
        steps.append({"title": "What the AI looked at",
                      "text": "The AI pre-score was computed but is withheld at this site until it is validated "
                              "locally; the explanation below rests on the measured cells only."})
    # 2 -- what the cells show
    if n:
        method = ("found from their stained membranes, because strong staining hides the nuclei"
                  if summary.get("detection") == "membranes" else "found from their nuclei")
        steps.append({"title": "What the cells show", "text": (
            f"{n} cells were {method}, and each cell's membrane was traced all the way round. "
            f"{_pct(pct.get('3+', 0))} have a complete, intense ring; {_pct(pct.get('2+', 0))} a complete "
            f"weak-to-moderate ring; {_pct(pct.get('1+', 0))} only faint, partial staining; and "
            f"{_pct(pct.get('0', 0))} no membrane staining.")})
    else:
        steps.append({"title": "What the cells show",
                      "text": "No cells could be measured in this field, so there is no cell-level evidence."})
    # 3 -- the ASCO/CAP rule
    if n:
        steps.append({"title": "Which ASCO/CAP rule this meets", "text": (
            f"By the {rule:.0f}% rule the cells put this field at IHC {summary.get('field_category')}: "
            f"{summary.get('rule_applied')}."
            + (" That is in the HER2-low range." if summary.get("her2_low") else "")
            + (" Faint staining in a few cells puts it in the HER2-ultralow range." if summary.get("her2_ultralow") else ""))})
    # 4 -- agreement
    if prescore and n:
        a, c = prescore["category"], summary.get("field_category")
        if a == c:
            text = f"The AI and the cell counts agree: both say IHC {a}."
        else:
            gap = abs(GRADES.index(a) - GRADES.index(c)) if a in GRADES and c in GRADES else None
            text = (f"The AI says IHC {a} but the cell counts say IHC {c}"
                    + (f" ({gap} grade{'s' if gap != 1 else ''} apart)" if gap else "")
                    + ". The AI judges the whole picture, including pattern and context; the cell rule counts "
                      "membranes against fixed cut points. When they differ, look at the example cells below and "
                      "at the regions where the AI weighed most.")
        steps.append({"title": "Do the AI and the cells agree?", "text": text})
    # 5 -- certainty
    if prescore:
        text = (f"Next most likely grade: {prescore['runner_up']}, "
                f"{round(prescore['margin_to_runner_up'] * 100)} percentage points behind.")
        if prescore.get("borderline"):
            text += " That is close: treat this field as borderline between the two grades."
        if (prescore.get("heterogeneity") or {}).get("heterogeneous"):
            text += " The regions disagree with each other (heterogeneous staining)."
        steps.append({"title": "How sure the system is", "text": text})
    # 6 -- what could change the answer
    cautions = list((guidance or {}).get("cautions") or [])
    if cautions:
        steps.append({"title": "What could change the answer", "text": " ".join(cautions[:5])})

    criteria = [
        {"grade": "3+", "definition": f"Complete, intense circumferential membrane staining in > {rule:.0f}% of "
                                      "invasive tumour cells", "measured": pct.get("3+", 0.0),
         "met": pct.get("3+", 0.0) > rule},
        {"grade": "2+", "definition": f"Weak-to-moderate complete membrane staining in > {rule:.0f}% of cells "
                                      "(or intense complete staining in ≤ 10%)", "measured": at2,
         "met": pct.get("3+", 0.0) <= rule and at2 > rule},
        {"grade": "1+", "definition": f"Incomplete, faint / barely perceptible membrane staining in > {rule:.0f}% "
                                      "of cells", "measured": at1, "met": at2 <= rule and at1 > rule},
        {"grade": "0", "definition": f"No staining, or incomplete faint staining in ≤ {rule:.0f}% of cells "
                                     "(HER2-ultralow when some faint staining is present)", "measured": at1,
         "met": at1 <= rule},
    ]
    definitions = [
        {"term": "Membrane completeness",
         "text": f"The ring around each cell is divided into {params.sectors} sectors; a sector counts as stained "
                 f"when its strongest DAB reaches the faint cut ({faint:.2f} OD). A cell is 'complete' when "
                 f"≥ {round(params.complete_fraction * 100)}% of its sectors are stained, and has 'some staining' "
                 f"from {round(params.any_fraction * 100)}%."},
        {"term": "Membrane intensity",
         "text": f"The median DAB of the stained sectors: weak from {faint:.2f}, strong from {strong:.2f} OD "
                 f"(moderate in between). Cut points calibrated on held-out HER2 IHC fields."},
        {"term": "Cell categories",
         "text": "3+ = complete and strong; 2+ = complete and weak-moderate (or strong but incomplete — flagged as "
                 "atypical); 1+ = some faint staining, incomplete; 0 = no membrane staining."},
        {"term": "Where the AI looked",
         "text": "The Evidence view shows the parts of the image that pushed the AI towards its grade (Grad-CAM); "
                 "the Regions view shows each region's own grade and how much it weighed in the result."},
    ]
    return {"steps": steps, "criteria": criteria, "definitions": definitions,
            "examples": _crop_examples(rgb, cells), "distributions": _distributions(records),
            "cut_points": {"faint": round(faint, 3), "strong": round(strong, 3), "rule_percent": rule}}
