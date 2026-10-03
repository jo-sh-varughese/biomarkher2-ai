"""Objective 1, across institutions and within a real slide: adaptive stain-vector analysis.

    python scripts/stain_variation_sites.py --per-site 100

Estimates the haematoxylin and DAB stain vectors (Macenko, the corrected
estimator in preprocessing/stains.py) per image for three real sources:

* HER2-IHC-40x -- our training dataset (held-out patches);
* BCI -- a second hospital (other scanner and staining protocol);
* ACROBAT case 39 -- a real HER2 IHC whole slide (Karolinska), sampled as
  tissue regions across the slide.

and reports, per source, the mean stain directions, the spread within the
source, and the angle between sources' mean vectors -- plus, for the whole
slide, how much the stain varies from region to region inside one slide.
Writes artifacts/phase4/stain_variation_sites.json and a plot.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from preprocessing.stains import estimate_macenko_stain_matrix, rgb_to_od  # noqa: E402


def unit(v):
    v = np.asarray(v, float)
    return v / (np.linalg.norm(v) + 1e-12)


def angle(a, b) -> float:
    return math.degrees(math.acos(max(-1.0, min(1.0, float(abs(unit(a) @ unit(b)))))))


def estimate(rgb: np.ndarray) -> dict | None:
    od = rgb_to_od(rgb).reshape(-1, 3)
    tissue = od.sum(1) > 0.15
    if tissue.sum() < 5000:
        return None
    m = estimate_macenko_stain_matrix(rgb, tissue.reshape(rgb.shape[:2]))
    conc = od[tissue] @ np.linalg.pinv(m)
    return {"h": unit(m[0]).tolist(), "dab": unit(m[1]).tolist(),
            "h_p99": float(np.percentile(conc[:, 0], 99)), "dab_p99": float(np.percentile(conc[:, 1], 99))}


def summarize(name: str, rows: list[dict]) -> dict:
    h = np.array([r["h"] for r in rows])
    d = np.array([r["dab"] for r in rows])
    hm, dm = unit(h.mean(0)), unit(d.mean(0))
    return {"source": name, "n": len(rows), "mean_h": hm.round(4).tolist(), "mean_dab": dm.round(4).tolist(),
            "h_spread_deg": round(float(np.median([angle(x, hm) for x in h])), 2),
            "dab_spread_deg": round(float(np.median([angle(x, dm) for x in d])), 2),
            "h_p99_median": round(float(np.median([r["h_p99"] for r in rows])), 3),
            "dab_p99_median": round(float(np.median([r["dab_p99"] for r in rows])), 3)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-site", type=int, default=100)
    ap.add_argument("--slide", default="data/slides/39_HER2_val.tif")
    ap.add_argument("--out", default="artifacts/phase4/stain_variation_sites.json")
    args = ap.parse_args()
    rng = random.Random(20261003)
    sources: dict[str, list[dict]] = {}

    files = sorted(f for f in glob.glob(str(ROOT / "data/raw/*/class_*/*")) if "_test_" in Path(f).name)
    rows = []
    for f in rng.sample(files, min(len(files), args.per_site * 2)):
        r = estimate(np.asarray(Image.open(f).convert("RGB")))
        if r:
            rows.append(r)
        if len(rows) >= args.per_site:
            break
    sources["HER2-IHC-40x (training site)"] = rows

    files = sorted(glob.glob(str(ROOT / "data/external/bci/IHC_test/*.png")))
    rows = []
    for f in rng.sample(files, min(len(files), args.per_site * 2)):
        r = estimate(np.asarray(Image.open(f).convert("RGB")))
        if r:
            rows.append(r)
        if len(rows) >= args.per_site:
            break
    sources["BCI (second hospital)"] = rows

    slide_path = ROOT / args.slide
    slide_rows = []
    if slide_path.is_file():
        from wsi.reader import Slide, tissue_overview_mask

        s = Slide(slide_path)
        ov, f = s.overview(8.0)
        mask = tissue_overview_mask(ov)
        tile = 512
        step = max(1, int(tile / f))
        cands = [(r, c) for r in range(0, mask.shape[0] - step, step) for c in range(0, mask.shape[1] - step, step)
                 if mask[r:r + step, c:c + step].mean() > 0.6]
        for r, c in rng.sample(cands, min(len(cands), args.per_site * 2)):
            rgb = s.read(int(c * f), int(r * f), tile, tile)
            est = estimate(rgb)
            if est:
                est["where"] = [int(r * f), int(c * f)]
                slide_rows.append(est)
            if len(slide_rows) >= args.per_site:
                break
        sources[f"ACROBAT case 39 whole slide ({len(cands)} tissue regions)"] = slide_rows

    summary = [summarize(k, v) for k, v in sources.items() if v]
    pairs = []
    for i in range(len(summary)):
        for j in range(i + 1, len(summary)):
            a, b = summary[i], summary[j]
            pairs.append({"a": a["source"], "b": b["source"],
                          "h_angle_deg": round(angle(a["mean_h"], b["mean_h"]), 2),
                          "dab_angle_deg": round(angle(a["mean_dab"], b["mean_dab"]), 2),
                          "dab_strength_ratio": round(b["dab_p99_median"] / max(1e-6, a["dab_p99_median"]), 3)})
    out = {"estimator": "Macenko (preprocessing/stains.py, eigenvector sign + H/DAB order fixed 2026-10-01)",
           "per_source": summary, "between_sources": pairs,
           "reading": "Within-source spread = median angle of each image's stain vector from its source mean. "
                      "Between-source angle = angle between source means. Between > within means the institutions' "
                      "stains differ by more than the image-to-image variation inside one institution."}
    Path(ROOT / args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(ROOT / args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    for s_ in summary:
        print(f"{s_['source']}: n={s_['n']}  H spread {s_['h_spread_deg']}°  DAB spread {s_['dab_spread_deg']}°  "
              f"H p99 {s_['h_p99_median']}  DAB p99 {s_['dab_p99_median']}")
    for p in pairs:
        print(f"{p['a']}  vs  {p['b']}: H {p['h_angle_deg']}°, DAB {p['dab_angle_deg']}°, DAB strength x{p['dab_strength_ratio']}")


if __name__ == "__main__":
    main()
