# ISH decision support and explainable AI

Status: built 2026-10-03, not committed. `app/decision.py`, `app/explain.py`,
UI `ui/src/components/DecisionPanel.jsx` + `ExplainPanel.jsx`, PDF pages in
`app/report.py` (`_decision_page`), whole slides via `wsi/analysis.py` and
`wsi/report.py`. Tests: `tests/test_decision.py`.

The panel follows the order in which a pathologist decides on ISH:

| Question | What the system shows | How it is computed |
|---|---|---|
| What does ASCO/CAP say for this result? | The algorithm (3+ / 2+ / 1+ / 0) with this case's step lit and its action | AI pre-score when shown, else cell evidence |
| What argues for and against ISH? | Weighted evidence (decisive / strong / moderate / supporting) | 2+ by AI or cells; AI-cell disagreement across 2+; share at the cut-off; unstable grade; heterogeneous 2+/3+ regions; AI borderline; stable concordant 3+ or 0/1+ |
| Can I trust this field? | Quality checklist (ok / check / fail) | Focus (Laplacian variance, calibrated on held-out fields: sharp 0.0003-0.0007, blurred < 0.0001), tissue %, cell count, detection method, site validation, magnification, AI-cell agreement, heterogeneity, atypical/cytoplasmic staining, on-slide control reminder |
| How close is it to 10%? | Each decisive share with its 95% Wilson interval against the 10% line | "At the cut-off" only when the share itself is 5-20%: a few cells alone widen the interval but call for more fields, not ISH |
| Would a slightly different reading change it? | Grade held under 27 nearby cut-point combinations | Every cell re-scored: faint cut ±15%, strong cut ±10%, completeness ±0.10 |
| What would it take to change the grade? | Exact cell counts | From the ASCO/CAP 10% rule and the counts |
| Where do I score ISH? | The highest-grade, highest-weight regions (fields) as images | AI regions (slide: hotspot fields) |
| How do I read the ISH result? | ASCO/CAP 2018 dual-probe groups 1-5 | Reference |

Clinical rules worth knowing:

* **0 vs 1+ is not an ISH question.** It decides HER2-low status (trastuzumab
  deruxtecan eligibility); the system flags that boundary separately and asks
  for high-power re-examination, not ISH.
* **Too few cells is not a reason for ISH.** It is a quality failure: score more
  fields of invasive tumour.
* A 3+ goes to "ISH recommended" only for reasons that question the grade
  (AI-cell disagreement, heterogeneity, borderline, atypical staining, cut-off
  proximity), never for cell count alone.
* A 0/1+ whose complete-membrane share is at the cut-off, or that becomes 2+
  under nearby cut points, is escalated to "consider ISH or a second review".

The PDF report carries all of this (ISH decision page, step-by-step
explanation, criteria check, example cells, ISH group reference) after the
summary page, for fields and whole slides.
