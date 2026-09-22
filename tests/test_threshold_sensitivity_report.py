"""Tests for scripts/threshold_sensitivity_report.py.

Uses a tiny synthetic manifest/split.json rather than a real cache, so this
runs in milliseconds and pins the exact arithmetic: pixel share must be the
tissue-weighted mean of each tile's own fraction, matching PHASE2.md's
"Training target pixel balance" table.
"""

from __future__ import annotations

import csv
import json

import pytest

from scripts.threshold_sensitivity_report import pixel_share

MANIFEST_FIELDS = [
    "patch_id",
    "parent_patch_id",
    "tissue_fraction",
    "frac_negative",
    "frac_weak",
    "frac_moderate",
    "frac_strong",
]


def _write_manifest(tmp_path, rows):
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    with (cache_root / "manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return cache_root


def _write_split(tmp_path, fit_ids):
    # Mirrors training/splits.py's Split.write() shape: id lists live under
    # "patch_ids", not at the top level -- an earlier version of this helper
    # used a flat {"fit": [...]} shape that didn't match the real file, which
    # is exactly how load_fit_patch_ids's key lookup bug shipped undetected.
    split_path = tmp_path / "split.json"
    split_path.write_text(
        json.dumps({"patch_ids": {"fit": fit_ids, "val": [], "holdout": []}}),
        encoding="utf-8",
    )
    return split_path


def test_pixel_share_matches_hand_computed_values(tmp_path):
    # One fit tile, half tissue, all of that tissue "moderate".
    rows = [
        {
            "patch_id": "a__r0c0",
            "parent_patch_id": "a",
            "tissue_fraction": "0.5",
            "frac_negative": "0",
            "frac_weak": "0",
            "frac_moderate": "1.0",
            "frac_strong": "0",
        }
    ]
    cache_root = _write_manifest(tmp_path, rows)
    split_path = _write_split(tmp_path, ["a"])

    result = pixel_share(cache_root, split_path)

    assert result["n_tiles"] == 1
    shares = result["shares"]
    assert shares["background"] == pytest.approx(0.5)
    assert shares["moderate (2+)"] == pytest.approx(0.5)
    assert shares["negative"] == pytest.approx(0.0)
    assert sum(shares.values()) == pytest.approx(1.0)


def test_pixel_share_only_counts_fit_tiles(tmp_path):
    rows = [
        {
            "patch_id": "a__r0c0",
            "parent_patch_id": "a",
            "tissue_fraction": "1.0",
            "frac_negative": "1.0",
            "frac_weak": "0",
            "frac_moderate": "0",
            "frac_strong": "0",
        },
        {
            # Not in the fit split -- must be excluded from the average.
            "patch_id": "b__r0c0",
            "parent_patch_id": "b",
            "tissue_fraction": "1.0",
            "frac_negative": "0",
            "frac_weak": "0",
            "frac_moderate": "0",
            "frac_strong": "1.0",
        },
    ]
    cache_root = _write_manifest(tmp_path, rows)
    split_path = _write_split(tmp_path, ["a"])

    result = pixel_share(cache_root, split_path)

    assert result["n_tiles"] == 1
    assert result["shares"]["negative"] == pytest.approx(1.0)
    assert result["shares"]["strong (3+)"] == pytest.approx(0.0)


def test_pixel_share_raises_when_no_fit_tiles_present(tmp_path):
    rows = [
        {
            "patch_id": "b__r0c0",
            "parent_patch_id": "b",
            "tissue_fraction": "1.0",
            "frac_negative": "1.0",
            "frac_weak": "0",
            "frac_moderate": "0",
            "frac_strong": "0",
        }
    ]
    cache_root = _write_manifest(tmp_path, rows)
    split_path = _write_split(tmp_path, ["a"])

    with pytest.raises(ValueError, match="No tiles"):
        pixel_share(cache_root, split_path)
