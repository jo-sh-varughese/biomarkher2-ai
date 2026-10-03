"""How many images does a stable site stain profile need?

    python scripts/profile_stability.py --site-dir data/external/bci --out artifacts/v2/profile_stability

Samples tissue pixels once from every image of a site, then refits the
site profile (evaluation/cross_site.py) many times from N randomly chosen
images and compares each with the profile from ALL images:

* DAB correction error: |gain_N / gain_all - 1|, where gain = reference DAB p99
  / site DAB p99 -- the number site normalization actually applies;
* stain-vector error: angle between the N-image and all-image H and DAB vectors.

The recommendation is the smallest N whose 95th-percentile DAB correction
error is under 5% and stain-vector error under 2 degrees.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from evaluation.cross_site import fit_site_profile, sample_tissue_pixels  # noqa: E402
from preprocessing.config import PreprocessingConfig  # noqa: E402
from preprocessing.tissue import detect_tissue  # noqa: E402


def angle(a, b) -> float:
    a, b = np.asarray(a), np.asarray(b)
    return float(np.degrees(np.arccos(np.clip(a @ b / np.linalg.norm(a) / np.linalg.norm(b), -1, 1))))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-dir", required=True)
    ap.add_argument("--sizes", default="5,10,20,50,100,200")
    ap.add_argument("--draws", type=int, default=30)
    ap.add_argument("--pixels", type=int, default=5000)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    prep = PreprocessingConfig.from_yaml(ROOT / "configs" / "preprocessing.yaml")
    rng = np.random.default_rng(0)
    paths = sorted(p for p in Path(args.site_dir).rglob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    samples = []
    for p in paths:
        rgb = np.asarray(Image.open(p).convert("RGB"))
        mask = detect_tissue(rgb, prep.tissue)
        if mask.sum() >= 1000:
            samples.append(sample_tissue_pixels(rgb, mask, args.pixels, rng))
    full = fit_site_profile(samples)
    reference_dab_p99 = json.loads((ROOT / "configs" / "site_profiles" / "her2_ihc_40x_vs_bci.json").read_text())["source"]["concentration_p99"][1]
    full_gain = reference_dab_p99 / full.concentration_p99[1]
    pick = random.Random(1)
    table = {}
    for n in [int(x) for x in args.sizes.split(",") if int(x) <= len(samples)]:
        gain_err, h_err, d_err = [], [], []
        for _ in range(args.draws):
            prof = fit_site_profile(pick.sample(samples, n))
            gain_err.append(abs((reference_dab_p99 / prof.concentration_p99[1]) / full_gain - 1))
            h_err.append(angle(prof.stain_matrix[0], full.stain_matrix[0]))
            d_err.append(angle(prof.stain_matrix[1], full.stain_matrix[1]))
        table[n] = {"dab_correction_error_median": float(np.median(gain_err)), "dab_correction_error_p95": float(np.percentile(gain_err, 95)),
                    "h_vector_error_deg_p95": float(np.percentile(h_err, 95)), "dab_vector_error_deg_p95": float(np.percentile(d_err, 95))}
        t = table[n]
        print(f"N={n:4d} images: DAB correction error median {100 * t['dab_correction_error_median']:.1f}% / 95th pct "
              f"{100 * t['dab_correction_error_p95']:.1f}% | stain-vector error 95th pct H {t['h_vector_error_deg_p95']:.2f} deg, "
              f"DAB {t['dab_vector_error_deg_p95']:.2f} deg", flush=True)
    ok = [n for n, t in table.items() if t["dab_correction_error_p95"] < 0.05 and max(t["h_vector_error_deg_p95"], t["dab_vector_error_deg_p95"]) < 2.0]
    recommendation = min(ok) if ok else None
    print("recommended minimum number of images:", recommendation)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps({"images_available": len(samples), "full_dab_gain": full_gain,
                                                  "table": table, "recommended_min_images": recommendation}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
