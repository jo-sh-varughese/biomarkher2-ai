"""Check the two cell-detector fixes (app/cells.py) before switching them on.

    python scripts/eval_cell_fixes.py

* diffuse_ratio: a cell whose cytoplasmic DAB matches its "membrane" DAB is not membrane-stained (counted 0).
* nucleus_area_cap: oversized "nuclei" (blue-tinted stroma blobs) are not cells.

Scored on the training site's FIT (20/class) and HOLDOUT (25/class) patches -- the same sets
scripts/calibrate_cells.py used -- with the calibrated cut points unchanged, so a fix is only kept if it does not
cost accuracy there. HER2match (artifacts/cell_diagnosis/*.npz) is reported for the diffuse rule only.
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

from app.cells import load_cell_params  # noqa: E402
from calibrate_cells import field_scores, measure  # noqa: E402
from evaluation.score_metrics import score_metrics  # noqa: E402
from preprocessing.config import PreprocessingConfig  # noqa: E402
from training.v2_data import her2_ihc_40x_samples  # noqa: E402


def main() -> None:
    prep = PreprocessingConfig.from_yaml(ROOT / "configs" / "preprocessing.yaml")
    split = ROOT / "configs" / "splits" / "her2_ihc_40x_split.json"
    base = load_cell_params(str(ROOT / "configs" / "cell_params.json"))
    sets = {"fit": her2_ihc_40x_samples(ROOT / "data" / "raw", split, "fit", 20, 11),
            "holdout": her2_ihc_40x_samples(ROOT / "data" / "raw", split, "holdout", 25, 0)}
    rows = []
    for cap in (None, 6000, 4000):
        detect = replace(base, nucleus_area_cap=cap)
        measured = {k: measure(v, prep, detect) for k, v in sets.items()}
        for ratio in (None, 0.7, 0.5):
            p = replace(detect, diffuse_ratio=ratio)
            res = {}
            for k, m in measured.items():
                mm = score_metrics([lab for lab, _ in m], field_scores(m, p, prep))
                res[k] = (round(mm["accuracy"], 3), round(mm["qwk"], 3))
            rows.append((cap, ratio, res))
            print(f"cap {cap}, diffuse {ratio}: FIT acc/QWK {res['fit']}, HOLDOUT acc/QWK {res['holdout']}", flush=True)
    # HER2match: diffuse rule only (sectors + cytoplasm OD were saved by diagnose_cells_her2match.py)
    from diagnose_cells_her2match import SLIDES, slide_call

    print("\nHER2match (inside marked regions), % cells 0/1+/2+/3+ -> call:")
    for ratio in (None, 0.7, 0.5):
        out = []
        for n in SLIDES:
            d = np.load(ROOT / "artifacts/cell_diagnosis" / f"{Path(n).stem}.npz")
            cats = []
            for sec, cyto in zip(d["sectors"], d["cyto"]):
                r = {"sector_max": sec, "cytoplasm_od": float(cyto)}
                from app.cells import classify_cell

                classify_cell(r, replace(base, diffuse_ratio=ratio), prep.stain.thresholds())
                cats.append(int(r["category"].rstrip("+")))
            cats = np.array(cats)
            pct = [round(100 * (cats == k).mean(), 1) for k in range(4)]
            out.append(f"{Path(n).stem[-3:]}(truth {['0','1+','2+','3+'][SLIDES[n]]}) {pct}->{['0','1+','2+','3+'][slide_call(cats)]}")
        print(f"  diffuse {ratio}: " + " | ".join(out))
    (ROOT / "artifacts" / "cell_diagnosis" / "fix_eval.json").write_text(json.dumps([(c, r, res) for c, r, res in rows]))


if __name__ == "__main__":
    main()
