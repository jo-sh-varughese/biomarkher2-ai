"""Simulation: does per-slide control calibration undo run-to-run DAB variation?

    python scripts/simulate_control_calibration.py [--per-class 40] [--runs 16]

Our own held-out patches are split into simulated staining runs. Each run gets
a random DAB strength (x0.5-x1.6) and haematoxylin strength (x0.85-x1.2), and
its own 3+ control (one fixed 3+ patch from the FIT split, stained the same
way). The model (Run A) scores five versions of every patch:

  original        -- unshifted (what the model was trained on)
  shifted         -- after the run's staining shift, uncorrected
  site_level      -- one pooled correction for all runs (site normalization)
  control_cal     -- per-run correction from that run's control (this module)
  oracle          -- the exact inverse of the shift (upper bound)
"""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402

from evaluation.control_calibration import apply_dab_gain, calibration_gain, control_signature  # noqa: E402
from evaluation.score_metrics import score_metrics  # noqa: E402
from preprocessing.config import PreprocessingConfig  # noqa: E402
from preprocessing.stains import deconvolve  # noqa: E402
from preprocessing.tissue import detect_tissue  # noqa: E402
from training.v2_data import Sample, her2_ihc_40x_samples  # noqa: E402
from training.v2_engine import load_model, predict  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=40)
    ap.add_argument("--runs", type=int, default=16)
    ap.add_argument("--checkpoint", default="artifacts/v2/run_a/best.pt")
    ap.add_argument("--out", default="artifacts/v2/control_calibration_sim")
    args = ap.parse_args()
    torch.set_num_threads(4)
    rng = random.Random(7)
    prep = PreprocessingConfig.from_yaml(ROOT / "configs" / "preprocessing.yaml")
    split = ROOT / "configs" / "splits" / "her2_ihc_40x_split.json"
    test = her2_ihc_40x_samples(ROOT / "data" / "raw", split, "holdout", args.per_class, 0)
    # The control: the most strongly stained of 20 random 3+ FIT patches (never a test patch).
    fit3 = [s for s in her2_ihc_40x_samples(ROOT / "data" / "raw", split, "fit", 20, 1) if s.label == 3]
    def dab_p90(p):
        rgb = np.asarray(Image.open(p).convert("RGB")); t = detect_tissue(rgb, prep.tissue)
        return float(np.percentile(deconvolve(rgb)[..., 1][t], 90)) if t.any() else 0.0
    control_path = max((s.path for s in fit3), key=dab_p90)
    control = np.asarray(Image.open(control_path).convert("RGB"))
    reference = control_signature(control, prep)

    runs = []
    for r in range(args.runs):
        g = math.exp(rng.uniform(math.log(0.5), math.log(1.6)))
        h = rng.uniform(0.85, 1.2)
        sig = control_signature(apply_dab_gain(control, g, h), prep)
        runs.append({"dab_gain": g, "h_gain": h, "control_gain": calibration_gain(sig, reference)})
    order = list(range(len(test)))
    rng.shuffle(order)
    assign = {i: order.index(i) % args.runs for i in range(len(test))}

    # site-level: one pooled DAB correction from all shifted images vs the unshifted pool (no labels)
    shifted_imgs, orig_dab, shift_dab = {}, [], []
    for i, s in enumerate(test):
        rgb = np.asarray(Image.open(s.path).convert("RGB"))
        run = runs[assign[i]]
        sh = apply_dab_gain(rgb, run["dab_gain"], run["h_gain"])
        shifted_imgs[i] = (rgb, sh)
        t = detect_tissue(rgb, prep.tissue)
        orig_dab.append(deconvolve(rgb)[..., 1][t][::50]); shift_dab.append(deconvolve(sh)[..., 1][detect_tissue(sh, prep.tissue)][::50])
    site_gain = float(np.percentile(np.concatenate(orig_dab), 99) / np.percentile(np.concatenate(shift_dab), 99))

    tmp = Path(tempfile.mkdtemp())
    conditions = {k: [] for k in ("original", "shifted", "site_level", "control_cal", "oracle")}
    for i, s in enumerate(test):
        rgb, sh = shifted_imgs[i]
        run = runs[assign[i]]
        versions = {"original": rgb, "shifted": sh, "site_level": apply_dab_gain(sh, site_gain),
                    "control_cal": apply_dab_gain(sh, run["control_gain"]),
                    "oracle": apply_dab_gain(sh, 1 / run["dab_gain"], 1 / run["h_gain"])}
        for k, img in versions.items():
            p = tmp / f"{k}_{i}.png"
            Image.fromarray(img).save(p)
            conditions[k].append(Sample(str(p), s.site, s.label, s.slide_label, s.has_seg, s.view))
    model = load_model(ROOT / args.checkpoint, torch.device("cpu"))
    results = {"runs": runs, "site_gain": site_gain, "control_patch": control_path, "reference_control": reference, "conditions": {}}
    for k, samples in conditions.items():
        rows = predict(model, samples, torch.device("cpu"), prep, 2, 0)
        m = score_metrics([r["label"] for r in rows], [r["pred"] for r in rows])
        results["conditions"][k] = m
        print(f"{k:12s} acc {m['accuracy']:.3f} bal {m['balanced_accuracy']:.3f} QWK {m['qwk']:.3f} big errors {np.mean([abs(r['pred']-r['label'])>=2 for r in rows]):.3f}", flush=True)
    gains = np.array([[r["dab_gain"], r["control_gain"]] for r in runs])
    results["control_gain_vs_true_inverse_corr"] = float(np.corrcoef(1 / gains[:, 0], gains[:, 1])[0, 1])
    print("correlation of control-estimated gain with the true inverse gain:", round(results["control_gain_vs_true_inverse_corr"], 3))
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
