"""Fingerprint a new hospital's images against the training site.

    python scripts/site_fingerprint.py --site-dir <folder> --site-mpp 0.46 --out artifacts/fingerprints/bci

Measures magnification (from microns-per-pixel), sharpness, JPEG quality,
noise, background brightness, stain colours and H/DAB intensity on UNLABELLED
images, and writes fingerprint.json plus a readable report.md listing the
corrections the pipeline will apply and anything that needs a human check.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.site_fingerprint import compare, site_fingerprint  # noqa: E402
from preprocessing.config import PreprocessingConfig  # noqa: E402

# HER2-IHC-40x: 3DHistech Pannoramic DESK at 40x (Nabi et al., Data in Brief 2025).
TRAINING_SITE_MPP = 0.24
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff")


def _fmt(value, spec=".1f"):
    return "-" if value is None else (format(value, spec) if isinstance(value, (int, float)) else str(value))


def run(site_dir: str, out: str, site_mpp: float | None = None, reference_dir: str | None = None,
        reference_mpp: float = TRAINING_SITE_MPP, max_images: int = 40) -> dict:
    prep = PreprocessingConfig.from_yaml(ROOT / "configs" / "preprocessing.yaml")
    rng = random.Random(0)
    ref_paths = sorted(Path(reference_dir or ROOT / "data" / "raw").glob("*/class_*/*.png"))
    site_paths = sorted(p for p in Path(site_dir).rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES)
    rng.shuffle(ref_paths)
    rng.shuffle(site_paths)
    reference = site_fingerprint(ref_paths[:max_images], prep, max_images=max_images, with_scale_curve=True)
    site = site_fingerprint(site_paths[:max_images], prep, max_images=max_images)
    result = compare(site, reference, site_mpp=site_mpp, reference_mpp=reference_mpp)
    corrections = {k: v for k, v in result["corrections"].items() if k != "stain_normalization"}

    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"site": site, "reference": reference, "measurements": result["measurements"],
               "corrections": corrections, "flags": result["flags"]}
    (out_dir / "fingerprint.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    rows = [
        ("Images measured", site["n_images"], reference["n_images"]),
        ("File formats", ", ".join(site["formats"]), ", ".join(reference["formats"])),
        ("JPEG quality (estimated)", _fmt(site["jpeg_quality"], ".0f"), _fmt(reference["jpeg_quality"], ".0f")),
        ("Sharpness, native (Laplacian variance)", _fmt(site["sharpness_native"]), _fmt(reference["sharpness_native"])),
        ("Noise on bare glass", _fmt(site["noise_on_glass"], ".2f"), _fmt(reference["noise_on_glass"], ".2f")),
        ("Background RGB", site["background_rgb"], reference["background_rgb"]),
        ("Tissue fraction", _fmt(site["tissue_fraction"], ".2f"), _fmt(reference["tissue_fraction"], ".2f")),
        ("DAB-positive tissue fraction", _fmt(site["dab_positive_fraction"], ".3f"), _fmt(reference["dab_positive_fraction"], ".3f")),
    ]
    lines = [f"# Site fingerprint: {site_dir}", "", "| Property | New site | Training site |", "|---|---|---|",
             *[f"| {a} | {b} | {c} |" for a, b, c in rows], "", "## Measured differences", "",
             *[f"- {k}: {v}" for k, v in result["measurements"].items()], "", "## Corrections to apply", "",
             *[f"- {k}: {v}" for k, v in corrections.items()], "", "## Flags", "",
             *([f"- {f}" for f in result["flags"]] or ["- none"])]
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload | {"report": "\n".join(lines)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site-dir", required=True)
    parser.add_argument("--site-mpp", type=float, default=None, help="scanner microns per pixel of the new site, if known")
    parser.add_argument("--reference-dir", default=None)
    parser.add_argument("--reference-mpp", type=float, default=TRAINING_SITE_MPP)
    parser.add_argument("--max-images", type=int, default=40)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    print(run(args.site_dir, args.out, args.site_mpp, args.reference_dir, args.reference_mpp, args.max_images)["report"])


if __name__ == "__main__":
    main()
