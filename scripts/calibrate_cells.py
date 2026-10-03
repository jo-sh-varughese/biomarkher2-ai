"""Calibrate the cell-level membrane cut points (app/cells.py) on the FIT split.

    python scripts/calibrate_cells.py [--per-class 20] [--holdout-per-class 25]

Cells are measured once per patch; the grid of (faint membrane OD, strong
membrane OD, completeness for "complete", completeness for "any") is then
searched for the best field-level agreement with the patch label on FIT
patches (accuracy, QWK as tie-break). The chosen setting is scored ONCE on
HOLDOUT patches and written to configs/cell_params.json, which app/cells.py
loads as its defaults.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from app.cells import CellParams, analyze_cells, classify_cell, summarize  # noqa: E402
from evaluation.score_metrics import score_metrics  # noqa: E402
from preprocessing.config import PreprocessingConfig  # noqa: E402
from preprocessing.tissue import detect_tissue  # noqa: E402
from training.v2_data import her2_ihc_40x_samples  # noqa: E402

CATS = ("0", "1+", "2+", "3+")


def measure(samples, prep, base):
    out = []
    for s in samples:
        rgb = np.asarray(Image.open(s.path).convert("RGB"))
        r = analyze_cells(rgb, detect_tissue(rgb, prep.tissue), prep.stain.thresholds(), base)
        out.append((s.label, r["cells"]))
    return out


def field_scores(measured, params, prep):
    preds = []
    for _, cells in measured:
        for c in cells:
            classify_cell(c, params, prep.stain.thresholds())
        preds.append(CATS.index(summarize(cells, params)["field_category"]))
    return preds


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=20)
    ap.add_argument("--holdout-per-class", type=int, default=25)
    args = ap.parse_args()
    prep = PreprocessingConfig.from_yaml(ROOT / "configs" / "preprocessing.yaml")
    split = ROOT / "configs" / "splits" / "her2_ihc_40x_split.json"
    base = CellParams()
    fit = measure(her2_ihc_40x_samples(ROOT / "data" / "raw", split, "fit", args.per_class, 11), prep, base)
    y = [label for label, _ in fit]
    best = None
    for faint, strong, complete, any_ in itertools.product((0.10, 0.15, 0.20, 0.25), (0.45, 0.55, 0.65, 0.80),
                                                           (0.5, 0.6, 0.75), (0.10, 0.15, 0.25)):
        if strong <= faint + 0.15:
            continue
        p = replace(base, membrane_faint=faint, membrane_strong=strong, complete_fraction=complete, any_fraction=any_)
        m = score_metrics(y, field_scores(fit, p, prep))
        key = (round(m["accuracy"], 4), round(m["qwk"], 4))
        if best is None or key > best[0]:
            best = (key, p, m)
    (_, chosen, fit_m) = best
    print(f"FIT ({len(y)} patches): acc {fit_m['accuracy']:.3f} QWK {fit_m['qwk']:.3f} with faint {chosen.membrane_faint} "
          f"strong {chosen.membrane_strong} complete {chosen.complete_fraction} any {chosen.any_fraction}", flush=True)
    hold = measure(her2_ihc_40x_samples(ROOT / "data" / "raw", split, "holdout", args.holdout_per_class, 0), prep, chosen)
    hm = score_metrics([label for label, _ in hold], field_scores(hold, chosen, prep))
    print(f"HOLDOUT ({hm['n']} patches, scored once): acc {hm['accuracy']:.3f} bal {hm['balanced_accuracy']:.3f} "
          f"QWK {hm['qwk']:.3f} confusion {hm['confusion']}", flush=True)
    out = {k: v for k, v in asdict(chosen).items()}
    out["calibration"] = {"fit_patches": len(y), "fit_accuracy": fit_m["accuracy"], "fit_qwk": fit_m["qwk"],
                          "holdout_patches": hm["n"], "holdout_accuracy": hm["accuracy"], "holdout_qwk": hm["qwk"],
                          "holdout_confusion": hm["confusion"]}
    (ROOT / "configs" / "cell_params.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("wrote configs/cell_params.json")


if __name__ == "__main__":
    main()
