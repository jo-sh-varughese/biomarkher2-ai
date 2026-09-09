"""ASCO/CAP score mapping, and why this stays out of the live viewer.

Objective 3 asks to "map AI predictions to CAP/ASCO-CAP HER2 score and
evaluate agreement with expert ground truth." This module implements the
mapping and the agreement evaluation as an OFFLINE, evaluation-time tool --
never wired into app/analysis.py or the live viewer's API response.

That split is deliberate and load-bearing, not a shortcut. This project's one
enforced rule (see IMPLEMENTATION_NOTES.md, "The one rule everything else
follows") is that no code path anywhere produces a field called "score",
"her2_score", "verdict" or "diagnosis" -- tests/test_app.py scans the live
API response for exactly those keys and fails if any appear. A live
"cap_score" field in the viewer would be that same rule, violated under a
different key name. So the mapping lives here, for scripts and reports a
human reads and reasons about offline -- not for the tool a pathologist has
open while looking at a slide.

THE DENOMINATOR PROBLEM
=========================
ASCO/CAP scoring is defined on the PERCENTAGE OF TUMOUR CELLS showing
membrane staining (Wolff et al., 2018, J Clin Oncol). Nothing in this
project measures tumour cells: preprocessing/baseline.py reports percentage
of TISSUE AREA, which includes stroma, and the two diverge whenever stroma
content varies (see app/analysis.py's DENOMINATOR_CAVEAT, which already says
this for the live viewer). :func:`map_to_cap_category` inherits that same
substitution and is therefore an approximation of the rule, not the rule --
every result it produces should be read as "what the ASCO/CAP thresholds
would say if tissue-area were tumour-cell area," not as a diagnosis.

WHAT EVALUATE_AGREEMENT CAN ACTUALLY EVALUATE, TODAY
=======================================================
There is no pathologist-assigned expert ground truth anywhere in this
project (the 84 Kottayam slides are not yet digitized).
:func:`evaluate_agreement` is written and tested against whatever two label
sequences it is given, so it is ready to run the day real expert labels
arrive. Run today, its only honest input is HER2_IHC_40X's own per-patch
folder label -- a bucket assigned by the dataset's authors, not a
pathologist scoring a case under ASCO/CAP. Any call site that uses it that
way MUST carry SELF_CONSISTENCY_CAVEAT alongside the result, never present
it as clinical validation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from preprocessing.baseline import CLASS_NAMES, TISSUE_CLASSES

CAP_CATEGORIES = ("0", "1+", "2+", "3+")

DENOMINATOR_CAVEAT = (
    "This mapping uses percentage of TISSUE AREA, not percentage of TUMOUR "
    "CELLS. ASCO/CAP scoring is defined on the latter. The two diverge "
    "whenever stroma content varies. This is an approximation of the "
    "ASCO/CAP rule, not the rule itself -- see evaluation/cap_mapping.py."
)

SELF_CONSISTENCY_CAVEAT = (
    "No pathologist-assigned expert ground truth exists in this project yet. "
    "Any agreement computed against HER2_IHC_40X's own folder label is "
    "dataset self-consistency, not clinical validation -- see "
    "evaluation/cap_mapping.py."
)

NOT_A_LIVE_FEATURE = (
    "This mapping is an offline evaluation tool. It is deliberately not "
    "exposed anywhere in app/ -- the live viewer's one enforced rule is that "
    "it never emits a score, verdict or diagnosis. See "
    "IMPLEMENTATION_NOTES.md and tests/test_app.py."
)


@dataclass(frozen=True)
class CapMappingResult:
    category: str
    """One of CAP_CATEGORIES."""

    rule_applied: str
    """Which ASCO/CAP clause decided this, in human terms."""

    strong_pct: float
    moderate_pct: float
    weak_pct: float


def map_to_cap_category(
    percentages: dict[str, float],
    complete_threshold_pct: float = 10.0,
) -> CapMappingResult:
    """Apply the ASCO/CAP 2018 focused-update thresholds to area percentages.

    ``percentages`` is keyed by the class names in
    ``preprocessing.baseline.CLASS_NAMES`` ("negative", "weak (1+)",
    "moderate (2+)", "strong (3+)"), each a percentage of tissue area, as
    produced by ``app.analysis.percentages`` /
    ``preprocessing.baseline.area_distribution``.

    Rule (Wolff et al. 2018), read directly onto tissue-area percentage in
    place of tumour-cell percentage -- see the module docstring's caveat:

    * 3+: more than ``complete_threshold_pct`` of area shows strong/complete
      staining.
    * 2+: at least ``complete_threshold_pct`` of area shows moderate-or-above
      staining, and the 3+ clause above did not already fire.
    * 1+: more than ``complete_threshold_pct`` of area shows weak-or-above
      staining, and neither clause above fired.
    * 0: none of the above.
    """
    strong_name = CLASS_NAMES[TISSUE_CLASSES[-1]]
    moderate_name = CLASS_NAMES[TISSUE_CLASSES[-2]]
    weak_name = CLASS_NAMES[TISSUE_CLASSES[-3]]

    strong = float(percentages.get(strong_name, 0.0))
    moderate = float(percentages.get(moderate_name, 0.0))
    weak = float(percentages.get(weak_name, 0.0))

    if strong > complete_threshold_pct:
        return CapMappingResult(
            "3+",
            f"strong-staining area {strong:.2f}% > {complete_threshold_pct}%",
            strong, moderate, weak,
        )
    if (moderate + strong) >= complete_threshold_pct:
        return CapMappingResult(
            "2+",
            f"moderate-or-above area {moderate + strong:.2f}% >= {complete_threshold_pct}%",
            strong, moderate, weak,
        )
    if (weak + moderate + strong) > complete_threshold_pct:
        return CapMappingResult(
            "1+",
            f"weak-or-above area {weak + moderate + strong:.2f}% > {complete_threshold_pct}%",
            strong, moderate, weak,
        )
    return CapMappingResult(
        "0",
        f"weak-or-above area {weak + moderate + strong:.2f}% <= {complete_threshold_pct}%",
        strong, moderate, weak,
    )


@dataclass(frozen=True)
class AgreementResult:
    n: int
    exact_agreement: float
    """Fraction of pairs where predicted == reference exactly."""

    within_one_category: float
    """Fraction within one ordinal step (0<->1+<->2+<->3+) -- the leniency the
    base paper's own literature review (Koopman et al.) treats as clinically
    meaningful, since adjacent-category disagreement is a different failure
    from a 0-vs-3+ miss."""

    confusion: dict[str, dict[str, int]]
    """reference category -> predicted category -> count."""

    weighted_kappa: float
    """Quadratic-weighted Cohen's kappa, the standard agreement statistic for
    ordinal categories with more than two levels (adjacent disagreement
    penalised less than a 0-vs-3+ one)."""


def evaluate_agreement(predicted: list[str], reference: list[str]) -> AgreementResult:
    """Agreement between two sequences of CAP_CATEGORIES labels.

    Neither sequence is assumed to be more "true" than the other by this
    function -- it reports symmetric agreement statistics. Which one, if
    either, is actually expert ground truth is the caller's caveat to carry
    (see SELF_CONSISTENCY_CAVEAT above).
    """
    if len(predicted) != len(reference):
        raise ValueError("predicted and reference must be the same length")
    n = len(predicted)
    if n == 0:
        raise ValueError("Cannot evaluate agreement over zero pairs.")
    for label in (*predicted, *reference):
        if label not in CAP_CATEGORIES:
            raise ValueError(
                f"Unknown CAP category {label!r}; expected one of {CAP_CATEGORIES}"
            )

    index = {c: i for i, c in enumerate(CAP_CATEGORIES)}
    confusion = {r: {p: 0 for p in CAP_CATEGORIES} for r in CAP_CATEGORIES}
    exact = 0
    within_one = 0
    for p, r in zip(predicted, reference):
        confusion[r][p] += 1
        if p == r:
            exact += 1
        if abs(index[p] - index[r]) <= 1:
            within_one += 1

    kappa = _quadratic_weighted_kappa(predicted, reference, CAP_CATEGORIES)

    return AgreementResult(
        n=n,
        exact_agreement=exact / n,
        within_one_category=within_one / n,
        confusion=confusion,
        weighted_kappa=kappa,
    )


def _quadratic_weighted_kappa(
    predicted: list[str], reference: list[str], categories: tuple[str, ...]
) -> float:
    index = {c: i for i, c in enumerate(categories)}
    k = len(categories)
    n = len(predicted)

    observed = np.zeros((k, k), dtype=np.float64)
    for p, r in zip(predicted, reference):
        observed[index[r], index[p]] += 1
    observed /= n

    row_marg = observed.sum(axis=1)
    col_marg = observed.sum(axis=0)
    expected = np.outer(row_marg, col_marg)

    weights = np.zeros((k, k), dtype=np.float64)
    for i in range(k):
        for j in range(k):
            weights[i, j] = ((i - j) ** 2) / ((k - 1) ** 2)

    numerator = float((weights * observed).sum())
    denominator = float((weights * expected).sum())
    if denominator == 0:
        return 1.0 if numerator == 0 else 0.0
    return 1.0 - numerator / denominator
