"""ISH decision support: how far to trust this IHC field, and what the evidence says about ISH.

A pathologist deciding on ISH asks five questions; each has a section here,
computed from measurements the analysis already made (nothing is guessed):

1. **Can I trust this field?** -- a quality checklist (focus, tissue, cell
   count, how cells were found, site validation, magnification, AI-cell
   agreement, heterogeneity, atypical or cytoplasmic staining).
2. **How close is it to a cut-off?** -- 95% Wilson confidence intervals for
   the share of cells that decides the grade, against the ASCO/CAP 10% line.
   A share of 9% from 47 cells is not "below 10%"; its interval is ~3-20%.
3. **Would a slightly different reading change it?** -- every cell is re-scored
   under 27 nearby cut-point combinations (faint +/-15%, strong +/-10%,
   completeness +/-0.10); the share of combinations that keep the grade is the
   robustness.
4. **What would it take to change the grade?** -- the number of cells that
   would have to be read differently to move one grade up or down.
5. **What does ASCO/CAP say, and where do I score ISH?** -- the algorithm with
   this case's path highlighted, the evidence for and against ISH with its
   weight, the regions to target, and the dual-probe ISH group reference for
   when the result comes back.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

GRADES = ("0", "1+", "2+", "3+")
RULE = 10.0
# Laplacian variance of the grey field inside tissue, measured 2026-10-03 on 60
# held-out HER2 fields (5th-95th pct 0.0003-0.0007) and the same fields blurred
# (sigma 2: 0.00005-0.00009).
FOCUS_WARN, FOCUS_FAIL = 0.0002, 0.00012


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for k/n, in percent."""
    if n <= 0:
        return 0.0, 100.0
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return round(100 * max(0.0, centre - half), 1), round(100 * min(1.0, centre + half), 1)


def focus_score(rgb: np.ndarray, tissue: np.ndarray) -> float | None:
    from scipy import ndimage

    g = rgb.astype(np.float32).mean(-1) / 255.0
    lap = ndimage.laplace(g)
    return float(lap[tissue].var()) if tissue.sum() > 1000 else None


def _category(records: list[dict], p, thresholds) -> str:
    from app.cells import classify_cell, summarize

    rescored = [classify_cell(dict(r), p, thresholds) for r in records]
    return summarize(rescored, p)["field_category"]


def robustness(records: list[dict], p, thresholds) -> dict:
    """Grade under 27 nearby cut-point combinations."""
    if not records:
        return {"runs": 0, "by_grade": {}, "stable_percent": None}
    faint0 = p.membrane_faint if p.membrane_faint is not None else thresholds[0]
    strong0 = p.membrane_strong if p.membrane_strong is not None else thresholds[2]
    counts = {g: 0 for g in GRADES}
    base = _category(records, p, thresholds)
    runs = 0
    for fm in (0.85, 1.0, 1.15):
        for sm in (0.9, 1.0, 1.1):
            for dc in (-0.1, 0.0, 0.1):
                q = replace(p, membrane_faint=faint0 * fm, membrane_strong=strong0 * sm,
                            complete_fraction=min(0.95, max(0.3, p.complete_fraction + dc)))
                counts[_category(records, q, thresholds)] += 1
                runs += 1
    return {"runs": runs, "by_grade": counts, "baseline_grade": base,
            "stable_percent": round(100 * counts[base] / runs)}


def counterfactuals(summary: dict) -> list[str]:
    """How many cells would have to be read differently to change the grade."""
    n = int(summary.get("cells_measured") or 0)
    if not n:
        return []
    c = summary.get("counts") or {}
    k3 = int(c.get("3+", 0))
    k2 = k3 + int(c.get("2+", 0))
    k1 = k2 + int(c.get("1+", 0))
    limit = math.floor(RULE / 100 * n)  # largest count that is still "<= 10%"
    need = limit + 1                    # smallest count that is "> 10%"
    grade = summary.get("field_category")
    out = []
    if grade == "3+":
        out.append(f"To fall to 2+, {k3 - limit} of the {k3} complete-intense cells would have to be read as weaker "
                   f"(at most {limit} of {n} may be 3+).")
    elif grade == "2+":
        out.append(f"To reach 3+, {need - k3} more cells would need complete, intense staining "
                   f"(now {k3}; more than {limit} of {n} needed).")
        out.append(f"To fall to 1+, {k2 - limit} of the {k2} cells with complete membranes would have to be read as "
                   "incomplete or absent.")
    elif grade == "1+":
        out.append(f"To reach 2+, {need - k2} more cells would need complete membrane staining (now {k2}).")
        out.append(f"To fall to 0, {k1 - limit} of the {k1} cells with any membrane staining would have to be read as "
                   "unstained.")
    else:
        out.append(f"To reach 1+, {need - k1} more cells would need faint membrane staining (now {k1}).")
    return out


def _target_regions(rgb: np.ndarray, prescore: dict | None, limit: int = 3) -> list[dict]:
    """Where to score ISH: the highest-grade, highest-weight regions, as crops."""
    from app.analysis import to_data_uri
    from app.prescore import TILE

    if not prescore:
        return []
    regions = [r for r in prescore.get("regions") or [] if r.get("category") in ("2+", "3+")]
    regions.sort(key=lambda r: (GRADES.index(r["category"]), r.get("attention") or 0), reverse=True)
    out = []
    h, w = rgb.shape[:2]
    for r in regions[:limit]:
        y0, x0 = r["row"] * TILE, r["col"] * TILE
        crop = rgb[y0:min(h, y0 + TILE), x0:min(w, x0 + TILE)]
        if crop.size == 0:
            continue
        out.append({"row": r["row"] + 1, "col": r["col"] + 1, "grade": r["category"],
                    "weight": round(100 * (r.get("attention") or 0)), "image": to_data_uri(crop, max_side=260)})
    return out


PATHWAY = [
    {"grade": "3+", "result": "HER2-positive",
     "action": "No ISH needed by ASCO/CAP. Consider ISH if staining is heterogeneous, the control is doubtful, or the "
               "AI and cell evidence disagree."},
    {"grade": "2+", "result": "Equivocal",
     "action": "Reflex ISH (dual-probe) on the same specimen is required, or repeat IHC on a new specimen."},
    {"grade": "1+", "result": "HER2-negative, HER2-low",
     "action": "No ISH. Report HER2-low: relevant to trastuzumab deruxtecan eligibility."},
    {"grade": "0", "result": "HER2-negative (HER2-0 or HER2-ultralow)",
     "action": "No ISH. Distinguish 0 from 1+ carefully at high power; note ultralow (faint staining in <= 10%)."},
]

ISH_GROUPS = [
    {"group": "1", "criteria": "HER2/CEP17 ≥ 2.0 and ≥ 4.0 HER2 signals/cell", "result": "Positive"},
    {"group": "2", "criteria": "HER2/CEP17 ≥ 2.0 and < 4.0 signals/cell",
     "result": "Negative, unless concurrent IHC 3+ (work-up with IHC in the same area)"},
    {"group": "3", "criteria": "HER2/CEP17 < 2.0 and ≥ 6.0 signals/cell",
     "result": "Positive if concurrent IHC 2+ or 3+; otherwise negative (recount by a second observer)"},
    {"group": "4", "criteria": "HER2/CEP17 < 2.0 and ≥ 4.0 and < 6.0 signals/cell",
     "result": "Negative unless concurrent IHC 3+ (comment on uncertain significance)"},
    {"group": "5", "criteria": "HER2/CEP17 < 2.0 and < 4.0 signals/cell", "result": "Negative"},
]


def decision_support(rgb: np.ndarray | None, tissue: np.ndarray | None, records: list[dict], summary: dict, params,
                     thresholds, prescore: dict | None, block: dict | None, scan_mpp_ok: bool = True) -> dict:
    """The ISH decision-support payload for one field (see module docstring)."""
    n = int(summary.get("cells_measured") or 0)
    c = summary.get("counts") or {}
    k3 = int(c.get("3+", 0))
    k2 = k3 + int(c.get("2+", 0))
    k1 = k2 + int(c.get("1+", 0))
    cell_grade = summary.get("field_category")
    ai_grade = prescore.get("category") if prescore else None
    grade = ai_grade or cell_grade

    # ---- 1. quality checklist
    qc = []
    f = focus_score(rgb, tissue) if rgb is not None and tissue is not None else None
    if f is not None:
        state = "fail" if f < FOCUS_FAIL else "warn" if f < FOCUS_WARN else "ok"
        qc.append({"check": "Focus", "status": state,
                   "detail": {"ok": "Sharp: membranes can be judged.",
                              "warn": "Slightly soft focus: faint membranes may be under-called.",
                              "fail": "Out of focus: rescan before scoring."}[state]})
    if tissue is not None:
        tissue_pct = 100 * float(tissue.mean())
        qc.append({"check": "Tissue in field", "status": "ok" if tissue_pct >= 20 else "warn" if tissue_pct >= 5 else "fail",
                   "detail": f"{tissue_pct:.0f}% of the field is tissue."})
    qc.append({"check": "Cells measured", "status": "ok" if n >= 100 else "warn" if n >= 30 else "fail",
               "detail": f"{n} cells" + ("" if n >= 100 else " — fewer than 100: percentages are unstable. Score more "
                                                             "fields of invasive tumour before deciding (this is not by "
                                                             "itself a reason for ISH).")})
    if summary.get("detection") == "membranes":
        qc.append({"check": "Cell detection", "status": "warn",
                   "detail": "Nuclei hidden by strong staining; cells were found from their membranes. "
                             "Cells without a closed ring are not counted."})
    if block is not None:
        gate = block.get("gate_status")
        qc.append({"check": "AI validated at this site", "status": "ok" if block.get("validated") else "warn",
                   "detail": "Validated locally." if block.get("validated") else
                   f"Not validated here ({gate}); the AI pre-score is withheld or research-only."})
    qc.append({"check": "Magnification", "status": "ok" if scan_mpp_ok else "fail",
               "detail": "20x or finer." if scan_mpp_ok else "Below 20x: membranes cannot be judged."})
    if ai_grade and cell_grade:
        gap = abs(GRADES.index(ai_grade) - GRADES.index(cell_grade))
        qc.append({"check": "AI and cells agree", "status": "ok" if gap == 0 else "warn" if gap == 1 else "fail",
                   "detail": f"AI {ai_grade}, cells {cell_grade}" + ("" if gap == 0 else f" ({gap} grade{'s' * (gap > 1)} apart)")})
    het = (prescore or {}).get("heterogeneity") or {}
    if het:
        qc.append({"check": "Uniform staining", "status": "warn" if het.get("heterogeneous") else "ok",
                   "detail": "Regions differ in grade: score and report the areas separately." if het.get("heterogeneous")
                   else "Regions agree with each other."})
    for flag in summary.get("flags") or []:
        if "atypical" in flag or "cytoplasmic" in flag:
            qc.append({"check": "Staining pattern", "status": "warn", "detail": flag})
    qc.append({"check": "On-slide control", "status": "info",
               "detail": "Not visible in a single field: confirm the control stained as expected before signing."})

    # ---- 2. statistical certainty around the 10% line
    certainty = []
    for name, k in (("complete, intense (3+)", k3), ("complete membrane (≥ 2+)", k2), ("any membrane staining (≥ 1+)", k1)):
        lo, hi = wilson(k, n)
        share = round(100 * k / n, 1) if n else 0.0
        straddles = lo <= RULE < hi
        # "Near the line" needs the measured share itself to be close (5-20%):
        # 0 of 26 cells has an interval reaching 13% only because few cells were
        # counted -- the remedy is more fields, not ISH.
        near = straddles and 5.0 <= share <= 20.0
        certainty.append({"measure": f"Cells with {name}", "share": share, "low": lo, "high": hi,
                          "straddles": straddles, "near": near,
                          "reading": ("above 10% with confidence" if lo > RULE else
                                      "below 10% with confidence" if hi <= RULE else
                                      "at the 10% cut-off: uncertain" if near else
                                      "probably below 10%: count more cells to be sure" if share < 5 else
                                      "probably above 10%: count more cells to be sure")})
    decisive = {"3+": 0, "2+": 1, "1+": 2, "0": 2}.get(cell_grade, 2)
    boundary = bool(n) and (certainty[decisive]["near"] or (decisive < 2 and certainty[decisive + 1]["near"]))

    # ---- 3. robustness, 4. what would change it
    rob = robustness(records, params, thresholds)
    # Near the 2+ (ISH) boundary: the share that separates this grade from 2+
    # is statistically uncertain, or nearby cut points turn it into 2+.
    flips_to_2 = bool(rob["runs"]) and cell_grade != "2+" and rob["by_grade"].get("2+", 0) / rob["runs"] >= 0.2
    near_2plus = bool(n) and ((cell_grade in ("0", "1+") and certainty[1]["near"])
                              or (cell_grade == "3+" and certainty[0]["near"]) or flips_to_2)
    what_if = counterfactuals(summary)

    # ---- 5. evidence for / against ISH
    for_ish, against = [], []
    if grade == "2+":
        for_ish.append({"text": f"The {'AI pre-score' if ai_grade else 'cell evidence'} is 2+ (equivocal): ASCO/CAP requires reflex ISH.", "weight": "decisive"})
    if ai_grade and cell_grade and ai_grade != cell_grade and "2+" in (ai_grade, cell_grade):
        for_ish.append({"text": f"AI ({ai_grade}) and cells ({cell_grade}) disagree across the 2+ boundary.", "weight": "strong"})
    # Two different boundaries: 1+/2+ and 2+/3+ decide ISH; 0/1+ decides HER2-low
    # status (trastuzumab deruxtecan eligibility) and never by itself calls for ISH.
    alt = [g for g, v in rob["by_grade"].items() if v and g != rob["baseline_grade"]] if rob["runs"] else []
    unstable = rob["stable_percent"] is not None and rob["stable_percent"] < 80
    ish_boundary = near_2plus or (cell_grade == "2+" and (certainty[0]["near"] or certainty[1]["near"]))
    if ish_boundary:
        for_ish.append({"text": "The cell share that separates this grade from 2+ is within statistical uncertainty "
                                "of the 10% cut-off.", "weight": "moderate"})
    if unstable and ("2+" in alt or "3+" in alt or rob["baseline_grade"] == "2+"):
        for_ish.append({"text": f"The cell grade changes under {100 - rob['stable_percent']}% of nearby cut points "
                                f"(to {', '.join(alt)}).", "weight": "moderate"})
    low_boundary = None
    if cell_grade in ("0", "1+") and (certainty[2]["near"] or (unstable and set(alt) <= {"0", "1+"} and alt)):
        low_boundary = ("The field sits at the 0 / 1+ boundary (HER2-0 vs HER2-low). This does not call for ISH, but it "
                        "decides HER2-low status and eligibility for trastuzumab deruxtecan: re-examine at high power "
                        "(x40) and score more fields before reporting.")
    if het.get("heterogeneous") and any(r.get("category") in ("2+", "3+") for r in (prescore or {}).get("regions") or []):
        for_ish.append({"text": "Heterogeneous staining with 2+/3+ regions: an amplified subclone is possible.", "weight": "moderate"})
    if prescore and prescore.get("borderline"):
        for_ish.append({"text": f"The AI is borderline between {prescore['category']} and {prescore['runner_up']}.", "weight": "moderate"})
    if grade == "3+" and not boundary and (rob["stable_percent"] or 0) >= 80 and (not ai_grade or ai_grade == cell_grade):
        against.append({"text": "A stable, concordant 3+: ASCO/CAP does not require ISH.", "weight": "strong"})
    if grade in ("0", "1+") and not boundary and (rob["stable_percent"] or 0) >= 80:
        against.append({"text": f"A stable {grade} well away from the 2+ boundary: HER2-negative by IHC.", "weight": "strong"})
    if prescore and prescore.get("confidence", 0) >= 0.9 and grade != "2+":
        against.append({"text": f"The AI is {round(prescore['confidence'] * 100)}% confident in {prescore['category']}.", "weight": "supporting"})

    path_grade = grade if grade in GRADES else None
    return {
        "qc": qc,
        "certainty": certainty,
        "boundary": boundary,
        "near_2plus": near_2plus,
        "her2_low_boundary": low_boundary,
        "robustness": rob,
        "what_if": what_if,
        "pathway": [{**s, "taken": s["grade"] == path_grade} for s in PATHWAY],
        "evidence_for_ish": for_ish,
        "evidence_against_ish": against,
        "ish_targets": (_target_regions(rgb, prescore) if rgb is not None and (grade in ("2+", "3+") or for_ish)
                        else []),
        "ish_groups": ISH_GROUPS,
        "basis": "AI pre-score" if ai_grade else "cell evidence",
    }
