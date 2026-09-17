"""Per-class pixel-share table for a pseudo-label cache, over the fit split.

tasks/person1_model_quality.md Task 2 asks: is moderate (2+)'s thin pixel
share (3.6% at baseline, see PHASE2.md) an artifact of where
`dab_od_moderate` cuts the DAB optical-density scale, before spending a
training run finding out? This reproduces PHASE2.md's "Training target pixel
balance" table (background/negative/weak/moderate/strong share of pixels,
over the fit split's tiles) for any pseudo-label cache built by
scripts/build_pseudo_labels.py, so several threshold variants can be
compared on this cheap, training-free number first.

    python scripts/threshold_sensitivity_report.py \\
        --cache data/cache/pseudo_labels_40x --split artifacts/phase2_unet/split.json

The split is threshold-independent (holdout/val assignment doesn't depend on
dab_od_moderate), so the same split.json is reused across the baseline and
every variant -- the point is to compare pixel share at matched patches, not
to also vary which patches are "fit".
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from preprocessing.baseline import CLASS_NAMES, TISSUE_CLASSES

BACKGROUND_CLASS = 0


def load_fit_patch_ids(split_path: Path) -> set[str]:
    payload = json.loads(split_path.read_text(encoding="utf-8"))
    # training/splits.py's Split.write() nests the id lists under "patch_ids"
    # (sibling keys are sizes/class_counts/caveats, not more ids).
    fit = payload.get("patch_ids", {}).get("fit")
    if fit is None:
        raise ValueError(
            f"{split_path} has no patch_ids.fit key -- not a training/splits.py split.json"
        )
    return set(fit)


def load_manifest_rows(cache_root: Path) -> list[dict[str, str]]:
    manifest_path = cache_root / "manifest.csv"
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def pixel_share(cache_root: Path, split_path: Path) -> dict[str, float]:
    """Mean per-class share of pixels (background + all tissue classes,
    summing to ~1.0) over every fit-split tile in this cache.

    Every retained tile is the same size (drop_partial=true in
    preprocessing.yaml drops ragged edges), so an unweighted mean of each
    tile's own fraction is exactly the pooled pixel share -- no need to
    re-read the label PNGs pixel by pixel.
    """
    fit_ids = load_fit_patch_ids(split_path)
    rows = load_manifest_rows(cache_root)
    fit_rows = [row for row in rows if row["parent_patch_id"] in fit_ids]
    if not fit_rows:
        raise ValueError(
            f"No tiles in {cache_root} belong to the fit split described by "
            f"{split_path} -- built from a different/incompatible split?"
        )

    tissue_fractions = [float(row["tissue_fraction"]) for row in fit_rows]
    shares = {CLASS_NAMES[BACKGROUND_CLASS]: 1.0 - sum(tissue_fractions) / len(fit_rows)}
    for cls in TISSUE_CLASSES:
        column = f"frac_{CLASS_NAMES[cls].split(' ')[0]}"
        values = [
            float(row["tissue_fraction"]) * float(row[column]) for row in fit_rows
        ]
        shares[CLASS_NAMES[cls]] = sum(values) / len(fit_rows)
    return {"n_tiles": len(fit_rows), "shares": shares}


def print_table(label: str, result: dict) -> None:
    print(f"\n{label} -- {result['n_tiles']} fit tiles")
    print(f"{'class':<16}{'share of pixels':>16}")
    for name, share in result["shares"].items():
        print(f"{name:<16}{share * 100:>15.1f}%")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True, type=Path, help="Pseudo-label cache root.")
    parser.add_argument(
        "--split", required=True, type=Path,
        help="split.json to define the fit set (threshold-independent, so the "
        "baseline run's split.json is normally what every variant should pass).",
    )
    parser.add_argument("--label", default=None, help="Label for the printed table.")
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    result = pixel_share(args.cache, args.split)
    print_table(args.label or str(args.cache), result)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"Wrote {args.json_out}")


if __name__ == "__main__":
    main()
