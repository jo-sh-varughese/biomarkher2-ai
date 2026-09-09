"""Tests for the offline ASCO/CAP mapping and agreement evaluation.

See tests/test_app.py for the companion guarantee that none of this is
reachable from the live viewer's API.
"""

from __future__ import annotations

import pytest

from evaluation.cap_mapping import evaluate_agreement, map_to_cap_category
from preprocessing.baseline import CLASS_NAMES

WEAK = CLASS_NAMES[2]
MODERATE = CLASS_NAMES[3]
STRONG = CLASS_NAMES[4]


# --------------------------------------------------------------------------
# map_to_cap_category
# --------------------------------------------------------------------------


def test_strong_staining_above_threshold_maps_to_3plus():
    result = map_to_cap_category({STRONG: 15.0, MODERATE: 0.0, WEAK: 0.0})
    assert result.category == "3+"


def test_3plus_threshold_is_strictly_greater_than():
    # Exactly at 10% does not qualify for 3+; it falls through to the 2+
    # clause instead, which is inclusive of 10%.
    result = map_to_cap_category({STRONG: 10.0, MODERATE: 0.0, WEAK: 0.0})
    assert result.category == "2+"


def test_2plus_threshold_is_inclusive():
    result = map_to_cap_category({STRONG: 0.0, MODERATE: 10.0, WEAK: 0.0})
    assert result.category == "2+"


def test_1plus_requires_strictly_greater_than_threshold():
    at_threshold = map_to_cap_category({STRONG: 0.0, MODERATE: 0.0, WEAK: 10.0})
    above_threshold = map_to_cap_category({STRONG: 0.0, MODERATE: 0.0, WEAK: 10.01})
    assert at_threshold.category == "0"
    assert above_threshold.category == "1+"


def test_zero_when_nothing_stains():
    result = map_to_cap_category({STRONG: 0.0, MODERATE: 0.0, WEAK: 0.0})
    assert result.category == "0"


def test_missing_keys_default_to_zero_percent():
    assert map_to_cap_category({}).category == "0"


def test_rule_applied_is_a_human_readable_explanation():
    result = map_to_cap_category({STRONG: 20.0})
    assert "strong" in result.rule_applied


# --------------------------------------------------------------------------
# evaluate_agreement
# --------------------------------------------------------------------------


def test_perfect_agreement_gives_kappa_one():
    labels = ["0", "1+", "2+", "3+", "0", "3+"]
    result = evaluate_agreement(labels, labels)
    assert result.exact_agreement == 1.0
    assert result.within_one_category == 1.0
    assert result.weighted_kappa == pytest.approx(1.0)


def test_agreement_reports_confusion_and_counts():
    predicted = ["0", "0", "3+", "2+"]
    reference = ["0", "1+", "3+", "1+"]
    result = evaluate_agreement(predicted, reference)

    assert result.n == 4
    assert result.exact_agreement == pytest.approx(2 / 4)
    assert result.within_one_category == pytest.approx(1.0)  # no pair differs by >1 step
    assert result.confusion["0"]["0"] == 1
    assert result.confusion["1+"]["0"] == 1
    assert result.confusion["3+"]["3+"] == 1
    assert result.confusion["1+"]["2+"] == 1


def test_a_0_vs_3plus_miss_counts_against_within_one_category():
    result = evaluate_agreement(["3+"], ["0"])
    assert result.exact_agreement == 0.0
    assert result.within_one_category == 0.0


def test_rejects_length_mismatch():
    with pytest.raises(ValueError, match="same length"):
        evaluate_agreement(["0"], ["0", "1+"])


def test_rejects_unknown_category():
    with pytest.raises(ValueError, match="Unknown CAP category"):
        evaluate_agreement(["4+"], ["0"])


def test_rejects_empty_input():
    with pytest.raises(ValueError, match="zero pairs"):
        evaluate_agreement([], [])
