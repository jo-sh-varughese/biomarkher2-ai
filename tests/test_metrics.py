"""Tests for the metrics accumulator.

The cases with teeth are the ones about absent classes and about accumulation:
a confusion matrix built one batch at a time must equal the same data seen at
once, and a class that never occurs must report None rather than a zero that
drags the mean down.
"""

from __future__ import annotations

import csv
import json

import numpy as np
import pytest
import torch

from training.metrics import ConfusionMatrix


def test_perfect_prediction_scores_one_everywhere():
    targets = np.array([[0, 1], [2, 3]])
    matrix = ConfusionMatrix(num_classes=5)
    matrix.update(targets, targets)

    assert matrix.pixel_accuracy() == 1.0
    for m in matrix.per_class()[:4]:
        assert m.iou == pytest.approx(1.0)
        assert m.dice == pytest.approx(1.0)


def test_iou_matches_a_hand_computed_value():
    # 6 true pixels of class 1, of which 4 predicted correctly; 2 pixels of
    # class 0 wrongly predicted as 1. IoU(1) = 4 / (6 + 6 - 4) = 0.5.
    targets = np.array([1] * 6 + [0] * 2)
    predictions = np.array([1] * 4 + [0] * 2 + [1] * 2)
    matrix = ConfusionMatrix(num_classes=5)
    matrix.update(targets, predictions)

    class_one = matrix.per_class()[1]
    assert class_one.iou == pytest.approx(0.5)
    assert class_one.recall == pytest.approx(4 / 6)
    assert class_one.precision == pytest.approx(4 / 6)


def test_absent_class_reports_none_not_zero():
    """Class 4 never occurs and is never predicted."""
    matrix = ConfusionMatrix(num_classes=5)
    matrix.update(np.zeros(10, dtype=int), np.zeros(10, dtype=int))

    strong = matrix.per_class()[4]
    assert strong.support == 0
    assert strong.iou is None
    assert strong.dice is None
    # ...and it must not be averaged in as a zero.
    assert matrix.mean_iou() == pytest.approx(1.0)


def test_a_class_predicted_but_never_present_scores_zero_not_none():
    """Predicting a class that is not there is a real error, not an absence."""
    matrix = ConfusionMatrix(num_classes=5)
    matrix.update(np.zeros(10, dtype=int), np.array([0] * 8 + [4] * 2))

    assert matrix.per_class()[4].iou == pytest.approx(0.0)
    assert matrix.per_class()[4].precision == pytest.approx(0.0)
    assert matrix.per_class()[4].recall is None


def test_accumulation_over_batches_equals_the_whole_at_once():
    rng = np.random.default_rng(0)
    targets = rng.integers(0, 5, size=(6, 8, 8))
    predictions = rng.integers(0, 5, size=(6, 8, 8))

    batched = ConfusionMatrix(num_classes=5)
    for i in range(0, 6, 2):
        batched.update(targets[i : i + 2], predictions[i : i + 2])

    whole = ConfusionMatrix(num_classes=5)
    whole.update(targets, predictions)

    assert np.array_equal(batched.matrix, whole.matrix)


def test_ignore_index_pixels_are_excluded():
    targets = np.array([0, 1, -100, -100])
    predictions = np.array([0, 1, 4, 4])
    matrix = ConfusionMatrix(num_classes=5, ignore_index=-100)
    matrix.update(targets, predictions)

    assert matrix.matrix.sum() == 2
    assert matrix.pixel_accuracy() == 1.0


def test_tissue_mean_iou_excludes_background():
    """Background is large and easy; including it flatters the model."""
    targets = np.array([0] * 100 + [1] * 10)
    predictions = np.array([0] * 100 + [0] * 10)  # every tissue pixel missed
    matrix = ConfusionMatrix(num_classes=5)
    matrix.update(targets, predictions)

    assert matrix.tissue_mean_iou() == pytest.approx(0.0)
    assert matrix.mean_iou() > matrix.tissue_mean_iou()


def test_accepts_torch_tensors():
    matrix = ConfusionMatrix(num_classes=5)
    matrix.update(torch.zeros(4, 4, dtype=torch.long), torch.zeros(4, 4, dtype=torch.long))
    assert matrix.matrix[0, 0] == 16


def test_rejects_mismatched_sizes():
    matrix = ConfusionMatrix(num_classes=5)
    with pytest.raises(ValueError, match="differ in size"):
        matrix.update(np.zeros(4), np.zeros(5))


def test_written_artifacts_round_trip(tmp_path):
    matrix = ConfusionMatrix(num_classes=5)
    matrix.update(np.array([0, 1, 1, 2]), np.array([0, 1, 2, 2]))

    matrix.write_json(tmp_path / "m.json")
    payload = json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))
    assert payload["per_class"][1]["support"] == 2
    assert payload["confusion_matrix"] == matrix.matrix.tolist()

    matrix.write_csv(tmp_path / "m.csv")
    rows = list(csv.DictReader((tmp_path / "m.csv").read_text(encoding="utf-8").splitlines()))
    assert rows[1]["name"] == "negative"

    matrix.write_confusion_csv(tmp_path / "c.csv")
    assert "true \\ predicted" in (tmp_path / "c.csv").read_text(encoding="utf-8")
