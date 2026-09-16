"""Batch/summary report for many HER2 IHC patches at once.

For demoing to the Kottayam stakeholder (or anyone else) without a live
pathologist clicking through images one at a time: runs the same
`Analyzer.analyze()` the live viewer uses (see app/analysis.py) over a
directory of patches, or an explicit list of them, and writes one CSV row per
patch.

This is a pre-scoring analysis report. Like every other output in this
project, it deliberately never emits a `score`, `her2_score`, `verdict`, or
`diagnosis` field -- see IMPLEMENTATION_NOTES.md's "The one rule everything
else follows". write_report() checks the CSV's actual field names for this
before writing anything, the same way tests/test_app.py checks the live
API's actual JSON.

    python scripts/batch_report.py --run-dir artifacts/phase2_unet \\
        --input-dir data/raw/test/class_2+ --output artifacts/batch_report.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analysis import Analyzer

FORBIDDEN_FIELDS = {"score", "her2_score", "verdict", "diagnosis"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def collect_image_paths(input_dir: Path | None, patch_ids: list[str] | None) -> list[Path]:
    if patch_ids:
        return [Path(p) for p in patch_ids]
    if input_dir is not None:
        return [
            path
            for path in sorted(input_dir.rglob("*"))
            if path.suffix.lower() in IMAGE_EXTENSIONS
        ]
    raise SystemExit("Provide --input-dir or --patch-ids.")


def run_batch_report(analyzer: Analyzer, image_paths: list[Path]) -> list[dict]:
    """Analyze every patch and return one summary row per patch.

    Reuses the existing analysis engine end to end (tiling, tissue
    detection, model inference, the classical baseline) -- this never
    reimplements any of that, only reshapes `PatchAnalysis.to_dict()` into a
    flat row.
    """
    rows = []
    for image_path in image_paths:
        image = np.array(Image.open(image_path).convert("RGB"))
        result = analyzer.analyze(image, patch_id=image_path.name).to_dict()

        row = {
            "patch_id": image_path.name,
            "tissue_percent": result["tissue_percent"],
        }
        for prefix, percentages in (
            ("model", result["model_percentages"]),
            ("baseline", result["baseline_percentages"]),
        ):
            for class_name, value in percentages.items():
                row[f"{prefix}_{class_name}_percent"] = value
        # The measurement app/analysis.py actually produces is
        # disagreement_percent -- the fraction of tissue pixels where the
        # model and the classical baseline land on different classes. An
        # earlier version of this script read result.get("agreement"),
        # a key PatchAnalysis.to_dict() never produces, so this column was
        # silently blank on every row it ever wrote. See PHASE6_NOTES.md.
        row["disagreement_percent"] = result["disagreement_percent"]
        rows.append(row)
    return rows


def check_no_forbidden_fields(fieldnames: list[str]) -> None:
    forbidden = {name.lower() for name in fieldnames if name.lower() in FORBIDDEN_FIELDS}
    if forbidden:
        raise RuntimeError(f"Forbidden output fields detected: {sorted(forbidden)}")


def write_report(rows: list[dict], output_path: Path) -> None:
    if not rows:
        raise SystemExit("No image files found.")

    fieldnames = list(rows[0].keys())
    check_no_forbidden_fields(fieldnames)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir", required=True,
        help="Training run directory (holds best.pt and resolved_config.yaml).",
    )
    parser.add_argument(
        "--input-dir", type=Path, default=None,
        help="Directory of patches to scan recursively (e.g. one class folder).",
    )
    parser.add_argument(
        "--patch-ids", nargs="+", default=None,
        help="Explicit list of patch file paths, instead of --input-dir.",
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/batch_report.csv"))
    parser.add_argument("--preprocessing-config", default="configs/preprocessing.yaml")
    args = parser.parse_args()

    if bool(args.input_dir) == bool(args.patch_ids):
        raise SystemExit("Provide exactly one of --input-dir or --patch-ids.")

    run_dir = Path(args.run_dir)
    analyzer = Analyzer(run_dir, run_dir / "resolved_config.yaml", args.preprocessing_config)

    image_paths = collect_image_paths(args.input_dir, args.patch_ids)
    rows = run_batch_report(analyzer, image_paths)
    write_report(rows, args.output)

    print(f"Batch report created: {args.output}")
    print(f"Images analyzed: {len(rows)}")


if __name__ == "__main__":
    main()
