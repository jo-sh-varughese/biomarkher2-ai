"""Suggested next steps for the pathologist, including whether ISH is indicated.

Follows the ASCO/CAP HER2 testing guideline for breast cancer (Wolff et al.,
J Clin Oncol 2018; affirmed in the 2023 update, which added HER2-low
reporting guidance):

* IHC 3+  -> HER2-positive; ISH not required.
* IHC 2+  -> equivocal; reflex ISH (same specimen) or repeat IHC on a new
             specimen is REQUIRED.
* IHC 1+  -> HER2-negative; HER2-low (relevant to trastuzumab deruxtecan).
* IHC 0   -> HER2-negative; distinguish 0 from 1+ carefully. "Ultralow"
             (faint, incomplete staining in >0% and <=10% of cells; the
             DESTINY-Breast06 definition) noted where the cell evidence shows it.

On top of that algorithm, this system adds the cautions it can measure:
low model confidence, a borderline pair of grades, disagreement between the
AI pre-score and the cell-level evidence, regional heterogeneity, too few
cells, atypical staining, and an unvalidated site. Each pushes the suggestion
toward ISH or a second review. Every line is a suggestion for the
pathologist's decision; none is a decision.
"""

from __future__ import annotations

GRADES = ("0", "1+", "2+", "3+")

GUIDANCE_CAVEAT = (
    "Suggestions only. The pathologist scores the case on invasive tumour (excluding in-situ carcinoma and "
    "edge or crush artefact), checks the on-slide controls, and decides on ISH according to ASCO/CAP and "
    "local policy."
)


def _distance(a: str | None, b: str | None) -> int | None:
    if a is None or b is None:
        return None
    return abs(GRADES.index(a) - GRADES.index(b))


def recommend(prescore: dict | None, cells: dict, gate: dict, extra_flags: list[str] | None = None,
              assessable: bool = True, near_2plus: bool = False) -> dict:
    """``prescore``: PrescoreResult.public() when it may be used, else None. ``cells``: app.cells summary.

    ``assessable=False`` (e.g. a slide scanned below ~20x) never yields a grade-based
    suggestion: an unassessable slide must not read as "ISH not indicated".
    """
    flags = list(cells.get("flags", [])) + list(extra_flags or [])
    cell_grade = cells.get("field_category")
    steps: list[str] = []
    cautions: list[str] = []

    if prescore is None:
        basis = "cell evidence"
        grade = cell_grade
        cautions.append("The AI pre-score is withheld at this site (not yet locally validated); "
                        "the suggestion below rests on measured cell evidence only.")
    else:
        basis = "AI pre-score"
        grade = prescore["category"]
        d = _distance(grade, cell_grade)
        if d is not None and d >= 2:
            cautions.append(f"AI pre-score {grade} and cell-level evidence {cell_grade} disagree by {d} grades.")
        elif d == 1:
            cautions.append(f"AI pre-score {grade} and cell-level evidence {cell_grade} differ by one grade.")
        if prescore["confidence"] < 0.70:
            cautions.append(f"Model confidence is low ({prescore['confidence']:.0%}).")
        if prescore["borderline"]:
            cautions.append(f"Borderline between {prescore['category']} and {prescore['runner_up']} "
                            f"(margin {prescore['margin_to_runner_up']:.0%}).")
        if prescore.get("heterogeneity", {}).get("heterogeneous"):
            share = prescore["heterogeneity"]["regions_by_grade"]
            cautions.append("Regional heterogeneity: " + ", ".join(f"{g} in {v:.0%} of regions" for g, v in share.items() if v > 0) + ".")
    cautions += flags

    if near_2plus:
        cautions.append("The cell evidence sits at the 2+ (ISH) boundary: within statistical uncertainty of the 10% "
                        "cut-off, or it becomes 2+ under nearby cut points (see ISH decision support).")
    # Only cautions that question the grade itself push a 3+ towards ISH; too few
    # cells or how they were detected call for more fields, not an ISH test.
    grade_doubts = [c for c in cautions if any(k in c for k in (
        "disagree", "differ by", "Borderline", "heterogeneity", "atypical", "boundary", "confidence is low"))]
    if grade == "3+":
        status = "HER2-positive range (IHC 3+)"
        if grade_doubts:
            ish = {"level": "recommended", "text": "ISH recommended to confirm: the 3+ suggestion carries the cautions listed."}
        else:
            ish = {"level": "not_indicated_by_ihc", "text": "ISH not required by ASCO/CAP for a confirmed IHC 3+."}
    elif grade == "2+":
        status = "Equivocal range (IHC 2+)"
        ish = {"level": "required", "text": "If the pathologist confirms 2+, reflex ISH on the same specimen (or repeat IHC on a new specimen) is required by ASCO/CAP."}
    elif grade in ("1+", "0"):
        status = "HER2-negative range (IHC 1+, HER2-low)" if grade == "1+" else "HER2-negative range (IHC 0)"
        near_2 = (near_2plus or (prescore is not None and prescore["probabilities"].get("2+", 0) >= 0.25)
                  or cells.get("percent_at_least_2plus", 0) > 10)
        if near_2 or any("disagree" in c for c in cautions):
            ish = {"level": "recommended", "text": "Consider ISH or a second review: evidence points toward the 2+ boundary."}
        else:
            ish = {"level": "not_indicated_by_ihc", "text": "ISH not indicated by a confirmed IHC 0/1+."}
    else:
        status, ish = "Not assessable", {"level": "not_applicable", "text": "Too little measurable tissue for a suggestion."}

    if grade == "1+":
        steps.append("Report as HER2-low if confirmed (relevant to eligibility for trastuzumab deruxtecan).")
    if grade == "0":
        if cells.get("her2_ultralow"):
            steps.append("Cell evidence shows faint, incomplete staining in <=10% of cells: consider HER2-ultralow vs IHC 0.")
        steps.append("Distinguish 0 from 1+ carefully at high magnification (ASCO/CAP 2023 update).")
    if grade == "2+":
        steps.append("Confirm membrane completeness and intensity in invasive tumour at high magnification.")
    steps.append("Verify the on-slide control and that scoring is restricted to invasive tumour.")
    if any("cells detected" in f for f in flags):
        steps.append("Score additional fields: this field has too few cells for stable percentages.")
    if prescore is not None and prescore.get("heterogeneity", {}).get("heterogeneous"):
        steps.append("Review the highlighted regions individually; report heterogeneity if confirmed.")

    if not assessable:
        status = "Not assessable at this magnification"
        ish = {"level": "not_applicable",
               "text": "No IHC-based ISH suggestion: membrane staining cannot be judged on this scan."}
        steps = ["Rescan the slide at 20x or 40x (0.5 um/px or finer) and analyse again before HER2 scoring.",
                 "Verify the on-slide control and that scoring is restricted to invasive tumour."]
    return {"basis": basis, "suggested_range": status, "ish": ish, "cautions": cautions,
            "next_steps": steps, "caveat": GUIDANCE_CAVEAT}
