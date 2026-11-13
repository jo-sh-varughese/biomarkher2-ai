"""Fit HER2match's stain profile (no labels) and write a profile file that also holds the existing ones.

    python scripts/fit_her2match_profile.py [--per-slide 40]

Uses tiles of HER2match's NON-held-out slides only (never 013, 015, 016, 025), pooled, exactly
like the BCI profile in scripts/cross_site_stain_eval.py. Output:
configs/site_profiles/her2_ihc_40x_vs_bci_her2match.json = her2_ihc_40x_vs_bci.json + "her2match".
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from evaluation.cross_site import fit_site_profile, sample_tissue_pixels  # noqa: E402
from preprocessing.config import PreprocessingConfig  # noqa: E402
from preprocessing.tissue import detect_tissue  # noqa: E402
from training.v2_data import HER2MATCH_HELDOUT  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default="data/external/her2match/IHC")
    p.add_argument("--per-slide", type=int, default=40)
    p.add_argument("--max-pixels", type=int, default=4000)
    a = p.parse_args()
    prep = PreprocessingConfig.from_yaml(ROOT / "configs" / "preprocessing.yaml")
    by_slide: dict[int, list[Path]] = {}
    for f in sorted((ROOT / a.root).rglob("*.jpg")):
        m = re.match(r"wsi(\d+)_", f.name)
        if m and int(m.group(1)) not in HER2MATCH_HELDOUT:
            by_slide.setdefault(int(m.group(1)), []).append(f)
    rng_py, rng = random.Random(0), np.random.default_rng(0)
    samples = []
    for slide, files in sorted(by_slide.items()):
        for f in rng_py.sample(files, min(a.per_slide, len(files))):
            rgb = np.asarray(Image.open(f).convert("RGB"))
            mask = detect_tissue(rgb, prep.tissue)
            if mask.sum() >= 1000:
                samples.append(sample_tissue_pixels(rgb, mask, a.max_pixels, rng))
    prof = fit_site_profile(samples, background_intensity=prep.stain.background_intensity,
                            macenko_alpha=prep.stain.macenko_alpha, macenko_beta=prep.stain.macenko_beta)
    base = json.loads((ROOT / "configs/site_profiles/her2_ihc_40x_vs_bci.json").read_text(encoding="utf-8"))
    base["her2match"] = prof.to_dict()
    out = ROOT / "configs/site_profiles/her2_ihc_40x_vs_bci_her2match.json"
    out.write_text(json.dumps(base, indent=2), encoding="utf-8")
    print(f"slides {sorted(by_slide)}; {prof.n_images} tiles; DAB p99 {prof.concentration_p99} vs source "
          f"{base['source']['concentration_p99']} -> {out}")


if __name__ == "__main__":
    main()
