"""Calibrate conformal prediction sets for the AI pre-score at one site.

    # the validated training site (uses the same calibration half as the evaluation)
    python scripts/calibrate_prescore_sets.py --run artifacts/v2/run_b
    # a new hospital: a CSV of its own labelled cases (path,label 0-3) analysed by this model
    python scripts/calibrate_prescore_sets.py --run artifacts/v2/run_b --site "GMC Kottayam" --cases kottayam.csv

Writes <run>/prescore_sets.json: for alpha in (0.05, 0.10, 0.20) the LAC
threshold q (grade k is in the set when 1 - p_k <= q), the site it is valid
for, and how many cases it rests on. The portal shows the 90% set next to the
pre-score only when the server's site matches (app/analysis.py).

Why per site: evaluation/cross_site_conformal.py showed that calibration from
one hospital does not carry its guarantee to another (95% promised, 82%
delivered at BCI for this model), while calibrating on 25 of the new
hospital's own labelled cases restored it (96%). See PHASE4.md, Objective 2.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from evaluation.cross_site_conformal import lac_scores, weighted_threshold  # noqa: E402

TRAINING_SITE = "HER2-IHC-40x (training site, UMMC)"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default="artifacts/v2/run_b")
    ap.add_argument("--site", default=TRAINING_SITE)
    ap.add_argument("--cases", default=None, help="CSV with columns probs (4 space-separated), label (0-3)")
    ap.add_argument("--seed", type=int, default=20261003)
    args = ap.parse_args()
    run = ROOT / args.run
    if args.cases:
        rows = list(csv.DictReader(open(args.cases, encoding="utf-8")))
    else:
        rows = [r for r in csv.DictReader(open(run / "predictions.csv", encoding="utf-8"))
                if r["set"] == "her2_ihc_40x_holdout" and r["condition"] == "raw"]
        labels = np.array([int(r["label"]) for r in rows])
        rng = np.random.default_rng(args.seed)  # same calibration half as scripts/conformal_cross_site.py
        cal = np.concatenate([rng.permutation(np.nonzero(labels == c)[0])[: (labels == c).sum() // 2] for c in range(4)])
        rows = [rows[i] for i in cal]
    probs = np.array([[float(x) for x in r["probs"].split()] for r in rows])
    labels = np.array([int(r["label"]) for r in rows])
    scores = lac_scores(probs, labels)
    out = {"site": args.site, "n_cases": int(len(labels)), "score": "LAC (1 - p)", "built": str(date.today()),
           "checkpoint": str(Path(args.run) / "best.pt"),
           "thresholds": {str(a): round(weighted_threshold(scores, np.ones(len(scores)), 1.0, a), 6)
                          for a in (0.05, 0.1, 0.2)}}
    (run / "prescore_sets.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
