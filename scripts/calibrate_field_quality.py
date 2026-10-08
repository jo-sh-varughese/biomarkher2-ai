"""Measure the field-quality metrics on real images so the thresholds in
app/field_quality.py rest on data, not guesses.

    python scripts/calibrate_field_quality.py

Groups that must PASS: HER2 IHC fields from the training site (all four
grades), BCI (a second site and scanner) and fields of a real HER2 whole slide.
Groups that must FAIL: fields of an H&E slide (wrong stain) and Ki-67 images
(nuclear DAB stain). Prints percentiles per metric and group and writes
artifacts/field_quality_calibration.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.field_quality import measure_image  # noqa: E402

rng = np.random.default_rng(20261008)
METRICS = ["colour_spread", "noise", "flat_fraction", "structure", "eosin_share", "foreign_fraction",
           "ink_fraction", "nuclear_pattern", "dab_share", "dark_fraction"]


def sample(paths, n):
    paths = sorted(paths)
    idx = rng.choice(len(paths), size=min(n, len(paths)), replace=False)
    return [paths[i] for i in idx]


def load(p):
    return np.array(Image.open(p).convert("RGB"))


def slide_fields(path, n, size=1024):
    from wsi.reader import Slide

    s = Slide(path)
    ov, f = s.overview(target_mpp=8.0)
    od = -np.log(np.clip(ov.astype(np.float32), 1, 255) / 255).mean(-1) > 0.15
    ys, xs = np.nonzero(od)
    out = []
    for _ in range(n * 5):
        if len(out) >= n:
            break
        k = rng.integers(len(ys))
        img = s.read(int(xs[k] * f), int(ys[k] * f), size, size, target_mpp=0.25 if s.info.mpp else None)
        if (-np.log(np.clip(img.astype(np.float32), 1, 255) / 255).mean(-1) > 0.15).mean() > 0.3:
            out.append(img)
    return out


groups: dict[str, list] = {}
train = list((ROOT / "data/raw/test").glob("class_*/*.png"))
if "--slides-only" not in sys.argv:
    groups["HER2-IHC-40x (pass)"] = [load(p) for p in sample(train, 120)]
if "--slides-only" not in sys.argv:
    groups["BCI IHC (pass)"] = [load(p) for p in sample(list((ROOT / "data/external/bci/IHC_test").glob("*.png")), 80)]
ki = list((ROOT / "data/external/ki67/BCData/images/test").glob("*.png")) + list((ROOT / "data/external/ki67/BCData/images/test").glob("*.jpg"))
if "--slides-only" not in sys.argv:
    groups["Ki-67 nuclear IHC (fail)"] = [load(p) for p in sample(ki, 40)]
if "--slides" in sys.argv:
    try:
        groups["HER2 whole slide fields (pass)"] = slide_fields(ROOT / "data/slides/39_HER2_val.tif", 12)
        groups["H&E slide fields (fail)"] = slide_fields(ROOT / "data/slides/39_HE_val.tif", 12)
    except Exception as e:  # openslide missing
        print("slides skipped:", e)

res = {}
for g, imgs in groups.items():
    ms = [measure_image(im) for im in imgs]
    res[g] = {}
    print(f"\n### {g}  (n={len(ms)})")
    for k in METRICS:
        v = np.array([m[k] for m in ms if m[k] is not None], dtype=float)
        if v.size == 0:
            continue
        q = np.percentile(v, [0, 5, 50, 95, 100])
        res[g][k] = [round(float(x), 4) for x in q]
        print(f"  {k:18s} min {q[0]:8.3f}  p5 {q[1]:8.3f}  med {q[2]:8.3f}  p95 {q[3]:8.3f}  max {q[4]:8.3f}")
out = ROOT / "artifacts/field_quality_calibration.json"
out.write_text(json.dumps(res, indent=1), encoding="utf-8")
print("\nwrote", out)
