"""Evaluate CAP/ASCO agreement between the model and recorded pathologist reviews.

    python scripts/evaluate_cap_agreement.py

Reads ``artifacts/reviews.jsonl`` -- the file app/server.py's ``/api/review``
route appends to every time a pathologist confirms a score in the viewer
(see app/README.md, "Reviews": "That file is the input Phase 4 needs for
Cohen's kappa -- pathologist score against model measurement, on fields a
pathologist actually looked at").

For each reviewed field, this reads the model area percentages the
pathologist was actually shown at review time -- ``measurements.model`` in
the logged entry (see app/static/app.js's ``submitReview``) -- maps them
through :func:`evaluation.cap_mapping.map_to_cap_category`, and compares that
to the reviewer's own recorded score with
:func:`evaluation.cap_mapping.evaluate_agreement`. Using the measurements
logged at review time, rather than re-running the model now, is deliberate:
it compares the pathologist against what they actually looked at, not
against a possibly-different result from a checkpoint that may have changed
since.

This is Objective 3's "evaluate agreement with expert ground truth" --
completely real and ready to run, honestly reporting zero rows until a
pathologist has actually used the viewer. See evaluation/cap_mapping.py's
module docstring for why this stays a script, never a live API field.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.cap_mapping import (
    CAP_CATEGORIES,
    DENOMINATOR_CAVEAT,
    evaluate_agreement,
    map_to_cap_category,
)

REFERENCE_IS_REAL_EXPERT_CAVEAT = (
    "Reference here is a pathologist's own recorded review from the live "
    "viewer, not dataset self-consistency -- but the model side still "
    "substitutes tissue-area for tumour-cell area; see DENOMINATOR_CAVEAT."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviews", default="artifacts/reviews.jsonl")
    parser.add_argument("--out", default="artifacts/phase4/cap_agreement.json")
    return parser.parse_args()


def _normalize_reviewer_score(score: str) -> str | None:
    """Map a REVIEW_CHOICES value onto CAP_CATEGORIES, or None if it is not one.

    "cannot assess from this field" is a legitimate reviewer answer (see
    app/server.py's REVIEW_CHOICES) and is excluded here, not coerced into a
    category it never claimed to be.
    """
    return score if score in CAP_CATEGORIES else None


def main() -> int:
    args = parse_args()
    path = Path(args.reviews)
    if not path.is_file():
        print(f"No reviews file at {path} yet -- nothing to evaluate.")
        print(
            "This is expected until a pathologist has used the viewer; see "
            "app/README.md's 'Reviews' section."
        )
        return 0

    predicted: list[str] = []
    reference: list[str] = []
    skipped = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            reviewer_score = _normalize_reviewer_score(str(entry.get("score", "")))
            model_pct = (entry.get("measurements") or {}).get("model")
            if reviewer_score is None or not model_pct:
                skipped += 1
                continue
            predicted.append(map_to_cap_category(model_pct).category)
            reference.append(reviewer_score)

    if not predicted:
        print(
            f"{path} has {skipped} entries, none usable yet (all 'cannot "
            "assess', or missing measurements)."
        )
        return 0

    result = evaluate_agreement(predicted, reference)
    payload = {
        "n": result.n,
        "skipped": skipped,
        "exact_agreement": round(result.exact_agreement, 4),
        "within_one_category": round(result.within_one_category, 4),
        "weighted_kappa": round(result.weighted_kappa, 4),
        "confusion_reference_rows_predicted_cols": result.confusion,
        "denominator_caveat": DENOMINATOR_CAVEAT,
        "reference_caveat": REFERENCE_IS_REAL_EXPERT_CAVEAT,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    print(f"n={result.n} (skipped {skipped})")
    print(f"exact agreement:      {result.exact_agreement:.3f}")
    print(f"within one category:  {result.within_one_category:.3f}")
    print(f"weighted kappa:       {result.weighted_kappa:.3f}")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
