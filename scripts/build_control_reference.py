"""Build the reference DAB signature used for per-slide control calibration.

    # default: pooled signature of 3+ patches of the training site (a PROXY for a 3+ control)
    python scripts/build_control_reference.py
    # recommended at a hospital: its own 3+ control images (crops of the on-slide control, any image files)
    python scripts/build_control_reference.py --images path/to/3plus_control_crops --level 3+ --source "GMC Kottayam 3+ control"

Writes configs/control_reference.json: the DAB optical-density percentiles (p50 ... p99) of the DAB-stained
tissue of a control of known HER2 level. wsi/analysis.py compares each slide's own on-slide control with it
(evaluation/control_calibration.py) and rescales that slide's DAB so the control matches the reference. The
correction is applied only when the laboratory declares its control level (``--control-level 3+``).

Honest note on the default: the training site's 3+ PATIENT patches are a proxy for a 3+ control (a control
cell line is typically more uniformly stained than a tumour). The calibration is only as good as the
reference, so a hospital should build its own from its own control tissue.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from evaluation.control_calibration import signature_from_dab  # noqa: E402
from preprocessing.config import PreprocessingConfig  # noqa: E402
from preprocessing.stains import deconvolve  # noqa: E402
from preprocessing.tissue import detect_tissue  # noqa: E402

PER_IMAGE_CAP = 20000   # DAB pixels kept per image so that no single large image dominates the pool


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", default=None, help="folder of control images; default: 3+ patches of the training site (fit split)")
    ap.add_argument("--level", default="3+", choices=["3+"])
    ap.add_argument("--n", type=int, default=40, help="images used (training-site default only)")
    ap.add_argument("--source", default=None)
    ap.add_argument("--out", default="configs/control_reference.json")
    ap.add_argument("--seed", type=int, default=20261006)
    args = ap.parse_args()

    prep = PreprocessingConfig.from_yaml(ROOT / "configs" / "preprocessing.yaml")
    if args.images:
        paths = sorted(p for p in Path(args.images).rglob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".tif", ".tiff"))
        source = args.source or f"images in {args.images}"
    else:
        from training.v2_data import her2_ihc_40x_samples

        split = ROOT / "configs" / "splits" / "her2_ihc_40x_split.json"
        samples = [s for s in her2_ihc_40x_samples(ROOT / "data" / "raw", split, "fit") if s.label == 3]
        rng = np.random.default_rng(args.seed)
        pick = rng.permutation(len(samples))[: args.n]
        paths = [Path(samples[i].path) for i in pick]
        source = args.source or "HER2-IHC-40x training site: 3+ patches of the fit split (a proxy for a 3+ control; never the holdout)"
    if not paths:
        raise SystemExit("No images found.")
    rng = np.random.default_rng(args.seed)
    thr = prep.stain.thresholds()[0]
    pool = []
    for p in paths:
        rgb = np.asarray(Image.open(p).convert("RGB"))
        dab = deconvolve(rgb)[..., 1][detect_tissue(rgb, prep.tissue)]
        stained = dab[dab >= thr]
        if stained.size > PER_IMAGE_CAP:
            stained = rng.choice(stained, PER_IMAGE_CAP, replace=False)
        pool.append(stained)
    sig = signature_from_dab(np.concatenate(pool))
    record = {"level": args.level, "source": source, "n_images": len(paths), "built": date.today().isoformat(),
              "dab_threshold": float(thr), **{k: round(v, 5) if isinstance(v, float) else v for k, v in sig.items()}}
    Path(ROOT / args.out).write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
