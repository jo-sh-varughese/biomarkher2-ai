"""Tests for the reviews.jsonl -> CAP agreement script.

Exercises the module's functions directly rather than shelling out to the
script, matching how the rest of this project tests scripts/*.py logic
(see e.g. training/train.py's own test suite, which imports and calls
functions rather than invoking the CLI).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import evaluate_cap_agreement as script  # noqa: E402


def test_normalize_reviewer_score_accepts_a_cap_category():
    assert script._normalize_reviewer_score("2+") == "2+"


def test_normalize_reviewer_score_rejects_cannot_assess():
    assert script._normalize_reviewer_score("cannot assess from this field") is None


def test_missing_reviews_file_exits_cleanly(tmp_path, capsys):
    # main() reads args via argparse against sys.argv; call it with a
    # constructed argv so this test does not depend on process invocation.
    sys.argv = ["evaluate_cap_agreement.py", "--reviews", str(tmp_path / "missing.jsonl")]
    assert script.main() == 0
    out = capsys.readouterr().out
    assert "nothing to evaluate" in out


def test_end_to_end_agreement_from_a_synthetic_reviews_file(tmp_path, capsys):
    reviews = tmp_path / "reviews.jsonl"
    entries = [
        {
            "patch_id": "a.png",
            "score": "3+",
            "measurements": {"model": {"negative": 0, "weak (1+)": 0, "moderate (2+)": 0, "strong (3+)": 20}},
        },
        {
            "patch_id": "b.png",
            "score": "0",
            "measurements": {"model": {"negative": 100, "weak (1+)": 0, "moderate (2+)": 0, "strong (3+)": 0}},
        },
        {
            # A "cannot assess" review must be excluded, not coerced.
            "patch_id": "c.png",
            "score": "cannot assess from this field",
            "measurements": {"model": {"negative": 50, "weak (1+)": 50, "moderate (2+)": 0, "strong (3+)": 0}},
        },
        {
            # Missing measurements must be skipped, not crash the script.
            "patch_id": "d.png",
            "score": "1+",
            "measurements": {},
        },
    ]
    with open(reviews, "w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")

    out_path = tmp_path / "cap_agreement.json"
    sys.argv = [
        "evaluate_cap_agreement.py",
        "--reviews", str(reviews),
        "--out", str(out_path),
    ]
    assert script.main() == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["n"] == 2  # only a.png and b.png are usable
    assert payload["skipped"] == 2
    assert payload["exact_agreement"] == 1.0  # both a and b map correctly
    assert "denominator_caveat" in payload
    assert "reference_caveat" in payload

    out = capsys.readouterr().out
    assert "n=2" in out
