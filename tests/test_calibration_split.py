"""Tests for the one-time split of the reserved holdout set."""

from __future__ import annotations

from evaluation.calibration_split import split_holdout_for_conformal


class FakeSource:
    def __init__(self, labels: dict[str, int]):
        self._labels = labels

    def label(self, patch_id: str) -> int:
        return self._labels[patch_id]


def holdout_source(per_class: int = 20) -> tuple[FakeSource, list[str]]:
    labels = {}
    for cls in (1, 2, 3, 4):
        for i in range(per_class):
            labels[f"holdout/class_{cls}/p{i:03d}"] = cls
    return FakeSource(labels), sorted(labels)


def test_split_covers_every_holdout_patch_exactly_once():
    source, holdout_ids = holdout_source()
    calibration, test = split_holdout_for_conformal(
        source, holdout_ids, calibration_fraction=0.4, seed=0
    )
    assert sorted(calibration + test) == holdout_ids
    assert not set(calibration) & set(test)


def test_split_approximates_the_requested_calibration_fraction():
    source, holdout_ids = holdout_source(per_class=100)
    calibration, test = split_holdout_for_conformal(
        source, holdout_ids, calibration_fraction=0.3, seed=1
    )
    fraction = len(calibration) / len(holdout_ids)
    assert abs(fraction - 0.3) < 0.05


def test_split_keeps_every_class_on_both_sides():
    source, holdout_ids = holdout_source(per_class=20)
    calibration, test = split_holdout_for_conformal(
        source, holdout_ids, calibration_fraction=0.5, seed=2
    )
    for cls in (1, 2, 3, 4):
        assert any(source.label(p) == cls for p in calibration)
        assert any(source.label(p) == cls for p in test)


def test_split_is_reproducible_for_a_fixed_seed():
    source, holdout_ids = holdout_source()
    first = split_holdout_for_conformal(source, holdout_ids, 0.4, seed=7)
    second = split_holdout_for_conformal(source, holdout_ids, 0.4, seed=7)
    assert first == second
