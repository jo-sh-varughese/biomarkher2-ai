"""Objective 2 experiment: stain-shift-weighted conformal prediction across institutions.

    python scripts/conformal_cross_site.py --run artifacts/v2/run_a
    python scripts/conformal_cross_site.py --run artifacts/v2/run_b

Uses the run's saved predictions (predictions.csv: per-image probabilities for
the HER2-IHC-40x holdout and BCI test) and measures each image's stain on the
local copy. Calibration = a stratified half of the holdout (seed fixed);
tests = the other half (same hospital) and the BCI test subset available
locally (configs/splits/bci_test_subset_338.txt). Run A never saw BCI, so it
is the cross-institution test proper; Run B (the deployed model) trained on
BCI's training split and is reported for reference.

Writes <out>/<run>.json and a markdown summary. Descriptors are cached in
<out>/descriptors.npz (stain is a property of the image, not of the run).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from evaluation.cross_site_conformal import GRADES, run  # noqa: E402
from evaluation.stain_shift import patch_stain_descriptor  # noqa: E402
from preprocessing.stains import rgb_to_od  # noqa: E402


def local(path: str) -> Path:
    return ROOT / path.replace("\\", "/").split("HER2_PROJECT/", 1)[-1]


def features(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """(descriptor 6-d, domain features 9-d) for one image."""
    rgb = np.asarray(Image.open(path).convert("RGB"))
    if max(rgb.shape[:2]) > 1024:
        rgb = rgb[:1024, :1024]
    od = rgb_to_od(rgb).reshape(-1, 3)
    tissue = od.sum(1) > 0.15
    desc = patch_stain_descriptor(rgb)
    mean_od = od[tissue].mean(0) if tissue.sum() > 100 else np.zeros(3)
    return desc, np.r_[desc, mean_od]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default="artifacts/v2/run_a")
    ap.add_argument("--out", default="artifacts/conformal_cross_site")
    ap.add_argument("--seed", type=int, default=20261003)
    args = ap.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(open(ROOT / args.run / "predictions.csv", encoding="utf-8")))
    rows = [r for r in rows if r["condition"] == "raw"]
    subset = {ln.strip() for ln in open(ROOT / "configs/splits/bci_test_subset_338.txt", encoding="utf-8") if ln.strip()}
    hold = [r for r in rows if r["set"] == "her2_ihc_40x_holdout"]
    bci = [r for r in rows if r["set"] == "bci_test" and Path(r["path"].replace("\\", "/")).name in subset]
    for r in bci:
        r["path"] = str(ROOT / "data/external/bci/IHC_test" / Path(r["path"].replace("\\", "/")).name)

    cache_path = out / "descriptors.npz"
    cache = dict(np.load(cache_path, allow_pickle=True)["d"].item()) if cache_path.is_file() else {}
    todo = [r for r in hold + bci if Path(r["path"]).name + r["set"] not in cache]
    for i, r in enumerate(todo, 1):
        p = local(r["path"]) if r["set"] != "bci_test" else Path(r["path"])
        cache[Path(r["path"]).name + r["set"]] = features(p)
        if i % 200 == 0:
            print(f"stain features {i}/{len(todo)}", flush=True)
            np.savez(cache_path, d=np.array(cache, dtype=object))
    np.savez(cache_path, d=np.array(cache, dtype=object))

    def arrays(rs):
        probs = np.array([[float(x) for x in r["probs"].split()] for r in rs])
        labels = np.array([int(r["label"]) for r in rs])
        desc = np.array([cache[Path(r["path"]).name + r["set"]][0] for r in rs])
        x = np.array([cache[Path(r["path"]).name + r["set"]][1] for r in rs])
        return probs, labels, x, desc

    rng = np.random.default_rng(args.seed)
    labels_h = np.array([int(r["label"]) for r in hold])
    cal_idx = np.concatenate([rng.permutation(np.nonzero(labels_h == c)[0])[: (labels_h == c).sum() // 2] for c in range(4)])
    in_idx = np.setdiff1d(np.arange(len(hold)), cal_idx)
    cal = arrays([hold[i] for i in cal_idx])
    tests = {"same_hospital (HER2-IHC-40x)": arrays([hold[i] for i in in_idx]), "other_hospital (BCI)": arrays(bci)}
    result = run(cal[0], cal[1], cal[2], cal[3], tests)
    from evaluation.cross_site_conformal import local_calibration

    bp, bl = tests["other_hospital (BCI)"][0], tests["other_hospital (BCI)"][1]
    result["site_onboarding_BCI"] = local_calibration(bp, bl, cal[0], cal[1])
    name = Path(args.run).name
    result.update({"run": args.run, "seed": args.seed, "score": "LAC (1 - p_true)", "grades": list(GRADES)})
    (out / f"{name}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    lines = [f"# Cross-institution conformal prediction -- {args.run}", "",
             f"Calibration: {result['n_calibration']} held-out images (training site).", ""]
    for tname, t in result["tests"].items():
        lines += [f"## {tname}: n={t['n']}, top-1 accuracy {t['top1_accuracy']}, domain AUC {t['domain_auc']}, "
                  f"effective calibration size {t['effective_calibration_size']}", "",
                  "| target coverage | method | coverage | mean set size | singletons |", "|---|---|---|---|---|"]
        for a, m in t["by_alpha"].items():
            for meth in ("unweighted", "kernel", "likelihood_ratio"):
                e = m[meth]
                lines.append(f"| {m['target']} | {meth} | {e['coverage']} | {e['mean_set_size']} | {e['singleton_rate']} |")
        lines.append("")
    lines += ["## Site onboarding: calibrate with k labelled cases from the new hospital (BCI), 50 random splits", "",
              "| k | target | method | coverage (mean) | coverage (10th pct) | mean set size | singletons |",
              "|---|---|---|---|---|---|---|"]
    for k, by_a in result["site_onboarding_BCI"].items():
        for a, d in by_a.items():
            for meth in ("local_only", "source_plus_local"):
                e = d[meth]
                lines.append(f"| {k} | {d['target']} | {meth} | {e['coverage_mean']} | {e['coverage_p10']} | "
                             f"{e['mean_set_size']} | {e['singleton_rate']} |")
    lines.append("")
    (out / f"{name}.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
