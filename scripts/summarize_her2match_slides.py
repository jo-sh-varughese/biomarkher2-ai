"""Combine HER2match whole-slide score files into one accuracy table with exact (Clopper-Pearson) 95% intervals.

    python scripts/summarize_her2match_slides.py artifacts/her2match_first4_rescored.json artifacts/her2match_pending_scores.json

Reports three calls per slide: the portal's primary score (cell-level ASCO/CAP rule), the cell category alone, and
the attention-pooled AI pre-score. HER2match is an unvalidated site (research mode); n is small, so the intervals
are the result, not the point estimates.
"""
from __future__ import annotations

import json
import sys

from scipy.stats import beta

GRADES = ("0", "1+", "2+", "3+")


def exact_ci(k: int, n: int) -> tuple[float, float]:
    lo = 0.0 if k == 0 else beta.ppf(0.025, k, n - k + 1)
    hi = 1.0 if k == n else beta.ppf(0.975, k + 1, n - k)
    return lo, hi


def main(paths: list[str]) -> int:
    rows = [r for p in paths for r in json.loads(open(p, encoding="utf-8").read())]
    ok = [r for r in rows if "error" not in r]
    for r in rows:
        if "error" in r:
            print(f"{r['slide']}: FAILED ({r['error']})")
    print(f"{'slide':10s} {'truth':5s} {'primary':7s} {'cells':5s} {'AI':4s} {'cells n':>7s} {'>=1+%':>6s} {'>=2+%':>6s} {'3+%':>5s}")
    for r in sorted(ok, key=lambda r: (GRADES.index(r["truth"]), r["slide"])):
        pc = r.get("cell_percentages") or {}
        by = pc.get("by_grade") or {}
        print(f"{r['slide']:10s} {r['truth']:5s} {str(r.get('primary_category')):7s} {str(r['cell_category']):5s} "
              f"{str(r['ai_prescore']):4s} {r.get('cells_measured') or 0:7d} {pc.get('at_least_1plus') or 0:6.1f} "
              f"{pc.get('at_least_2plus') or 0:6.1f} {by.get('3+') or 0:5.1f}")
    print()
    for key, label in (("primary_category", "Primary (cell rule)"), ("cell_category", "Cell category"), ("ai_prescore", "AI pre-score")):
        n = len(ok)
        k = sum(r.get(key) == r["truth"] for r in ok)
        lo, hi = exact_ci(k, n)
        # 0 vs HER2-low/positive, the treatment-relevant cut
        kb = sum((r.get(key) == "0") == (r["truth"] == "0") for r in ok if r.get(key) is not None)
        print(f"{label:20s} 4-class {k}/{n} = {k / n:.0%} (95% CI {lo:.0%}-{hi:.0%}); 0 vs >=1+ {kb}/{n}")
    # ISH safety: a truly 2+ slide must never be told "ISH not indicated"; a truly 0/1+ slide that gets an ISH or
    # review suggestion costs a test, not a missed treatment.
    pos = [r for r in ok if r["truth"] == "2+" and r.get("ish_level")]
    neg = [r for r in ok if r["truth"] in ("0", "1+") and r.get("ish_level")]
    missed = [r["slide"] for r in pos if r["ish_level"] == "not_indicated_by_ihc"]
    flagged = [r["slide"] for r in neg if r["ish_level"] in ("recommended", "required")]
    print(f"\nISH: 2+ slides told 'not indicated': {len(missed)}/{len(pos)} {missed}")
    print(f"ISH: 0/1+ slides sent to ISH/review: {len(flagged)}/{len(neg)} {flagged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
