"""Tests for pixel-level conformal prediction and its stain-shift weighting.

The most important property tested here is the one a silent bug would not
announce: the finite-sample coverage guarantee. A miscalibrated quantile
does not crash and does not look obviously wrong on a handful of examples --
it just means the prediction sets are wrong slightly more or less often than
claimed. :func:`test_conformal_prediction_achieves_nominal_coverage_on_average`
is the test that would catch that.
"""

from __future__ import annotations

import numpy as np
import pytest

from evaluation.conformal import (
    AMBIGUOUS,
    ClassCalibration,
    ConformalCalibrator,
    aggregate_patch_status,
    aggregate_patch_status_from_mask,
    checkpoint_fingerprint,
    evaluate_patch_statuses,
    evaluate_prediction_mask,
    evaluate_prediction_sets,
    hinge_scores,
    load_calibrator,
    prediction_mask,
    weighted_quantile,
)


# --------------------------------------------------------------------------
# hinge_scores
# --------------------------------------------------------------------------


def test_hinge_scores_is_one_minus_probability():
    probs = np.array([[0.9, 0.1], [0.2, 0.8]])
    np.testing.assert_allclose(hinge_scores(probs), 1.0 - probs)


def test_hinge_scores_rejects_a_single_class():
    with pytest.raises(ValueError, match="at least 2 classes"):
        hinge_scores(np.array([1.0]))


# --------------------------------------------------------------------------
# weighted_quantile
# --------------------------------------------------------------------------


def test_unweighted_quantile_matches_hand_computed_order_statistic():
    # n=4, alpha=0.5 -> ceil(5*0.5)=3rd smallest of [0.1,0.2,0.3,0.4] -> 0.3.
    assert weighted_quantile([0.4, 0.1, 0.3, 0.2], alpha=0.5) == pytest.approx(0.3)


def test_weighted_quantile_with_uniform_weights_equals_unweighted():
    rng = np.random.default_rng(0)
    scores = rng.uniform(size=25)
    alpha = 0.2
    assert weighted_quantile(scores, alpha, weights=np.ones(25)) == pytest.approx(
        weighted_quantile(scores, alpha)
    )


def test_weighted_quantile_rejects_bad_alpha():
    with pytest.raises(ValueError, match="alpha"):
        weighted_quantile([0.1, 0.2], alpha=1.5)


def test_weighted_quantile_rejects_empty_scores():
    with pytest.raises(ValueError, match="zero calibration"):
        weighted_quantile([], alpha=0.1)


def test_weighted_quantile_rejects_mismatched_weight_shape():
    with pytest.raises(ValueError, match="does not match"):
        weighted_quantile([0.1, 0.2, 0.3], alpha=0.1, weights=[1.0, 1.0])


def test_weighted_quantile_rejects_negative_weights():
    with pytest.raises(ValueError, match="non-negative"):
        weighted_quantile([0.1, 0.2], alpha=0.1, weights=[1.0, -1.0])


def test_weighted_quantile_returns_infinity_when_evidence_is_insufficient():
    # alpha so small that not even all calibration mass reaches (1 - alpha).
    q = weighted_quantile([0.1, 0.2, 0.3], alpha=0.01)
    assert q == float("inf")


def test_conformal_prediction_achieves_nominal_coverage_on_average():
    """The finite-sample guarantee, checked empirically rather than assumed.

    For exchangeable calibration and test nonconformity scores, inductive
    conformal prediction guarantees P(true class included) >= 1 - alpha.
    Draw many independent calibration sets and test points from the same
    distribution and check the empirical miscoverage rate lands close to
    alpha.
    """
    rng = np.random.default_rng(20260814)
    alpha = 0.1
    n_calibration = 60
    trials = 3000
    missed = 0
    for _ in range(trials):
        calibration_scores = rng.uniform(size=n_calibration)
        test_score = rng.uniform()
        q = weighted_quantile(calibration_scores, alpha)
        if test_score > q:
            missed += 1
    assert (missed / trials) == pytest.approx(alpha, abs=0.03)


# --------------------------------------------------------------------------
# ClassCalibration / ConformalCalibrator
# --------------------------------------------------------------------------


def test_class_calibration_rejects_empty_scores():
    with pytest.raises(ValueError, match="No calibration examples"):
        ClassCalibration(class_index=1, scores=np.array([]))


def test_class_calibration_rejects_mismatched_descriptors():
    with pytest.raises(ValueError, match="one row per calibration score"):
        ClassCalibration(
            class_index=1, scores=np.array([0.1, 0.2]), stain_descriptors=np.zeros((3, 6))
        )


def test_conformal_calibrator_prediction_set_includes_the_true_class_when_confident():
    calibrator = ConformalCalibrator.fit(
        {
            0: np.array([0.05, 0.06, 0.04, 0.05]),
            1: np.array([0.05, 0.06, 0.04, 0.05]),
            2: np.array([0.05, 0.06, 0.04, 0.05]),
        }
    )
    probs = np.array([0.97, 0.02, 0.01])
    assert calibrator.prediction_set(probs, alpha=0.2) == {0}


def test_prediction_sets_batch_matches_per_pixel_calls():
    calibrator = ConformalCalibrator.fit(
        {0: np.array([0.1, 0.2, 0.15]), 1: np.array([0.3, 0.25, 0.2])}
    )
    probs = np.array([[0.9, 0.1], [0.4, 0.6], [0.5, 0.5]])
    batch = calibrator.prediction_sets_batch(probs, alpha=0.3)
    singles = [calibrator.prediction_set(row, alpha=0.3) for row in probs]
    assert batch == singles


def test_stain_shift_weighting_favours_nearby_calibration_evidence():
    """Two clearly separated calibration 'sources': A has small nonconformity
    scores, B has large ones. A test point whose stain descriptor matches A
    should get a quantile close to A's alone, not blended evenly with B's --
    which is what the unweighted quantile over all the data does.
    """
    rng = np.random.default_rng(1)
    source_a_scores = rng.uniform(0.0, 0.1, size=100)
    source_b_scores = rng.uniform(0.8, 0.9, size=100)
    scores = np.concatenate([source_a_scores, source_b_scores])

    descriptor_a = np.array([1.0, 0, 0, 0, 1.0, 0])
    descriptor_b = np.array([-1.0, 0, 0, 0, -1.0, 0])
    descriptors = np.concatenate(
        [np.tile(descriptor_a, (100, 1)), np.tile(descriptor_b, (100, 1))]
    )

    calibration = ClassCalibration(class_index=0, scores=scores, stain_descriptors=descriptors)

    near_a = calibration.quantile(alpha=0.1, test_descriptor=descriptor_a, bandwidth=0.5)
    near_b = calibration.quantile(alpha=0.1, test_descriptor=descriptor_b, bandwidth=0.5)
    unweighted = calibration.quantile(alpha=0.1)

    assert near_a < unweighted < near_b
    assert near_a < 0.3
    assert near_b > 0.6


def test_omitting_stain_descriptor_falls_back_to_plain_conformal_prediction():
    calibration = ClassCalibration(class_index=0, scores=np.array([0.1, 0.2, 0.3]))
    plain = calibration.quantile(alpha=0.3)
    same = calibration.quantile(alpha=0.3, test_descriptor=np.zeros(6), bandwidth=1.0)
    assert plain == same


# --------------------------------------------------------------------------
# aggregate_patch_status
# --------------------------------------------------------------------------


def test_aggregate_patch_status_majority_class_wins():
    pixel_sets = [{1}] * 6 + [{2}] * 4
    assert aggregate_patch_status(pixel_sets) == 1


def test_aggregate_patch_status_is_ambiguous_on_a_tie():
    pixel_sets = [{1}] * 5 + [{2}] * 5
    assert aggregate_patch_status(pixel_sets) == AMBIGUOUS


def test_aggregate_patch_status_counts_multi_class_sets_as_ambiguous_pixels():
    pixel_sets = [{1}] * 4 + [{1, 2}] * 6
    assert aggregate_patch_status(pixel_sets) == AMBIGUOUS


def test_aggregate_patch_status_rejects_empty_input():
    with pytest.raises(ValueError, match="zero pixels"):
        aggregate_patch_status([])


# --------------------------------------------------------------------------
# evaluate_prediction_sets
# --------------------------------------------------------------------------


def test_evaluate_prediction_sets_computes_expected_metrics():
    pixel_sets = [{0}, {0}, {1}, {0, 1}, set()]
    true_classes = [0, 1, 1, 0, 1]
    metrics = evaluate_prediction_sets(pixel_sets, true_classes)
    assert metrics.miscoverage_rate == pytest.approx(2 / 5)
    assert metrics.ambiguity_rate == pytest.approx(2 / 5)
    assert metrics.accuracy == pytest.approx(2 / 3)
    assert metrics.n == 5


def test_evaluate_prediction_sets_accuracy_is_zero_when_everything_is_ambiguous():
    metrics = evaluate_prediction_sets([{0, 1}, set()], [0, 1])
    assert metrics.accuracy == 0.0


def test_evaluate_prediction_sets_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="same length"):
        evaluate_prediction_sets([{0}], [0, 1])


# --------------------------------------------------------------------------
# evaluate_patch_statuses
# --------------------------------------------------------------------------


def test_evaluate_patch_statuses_computes_expected_metrics():
    statuses = [1, 1, AMBIGUOUS, 2, 1]
    true_classes = [1, 2, 1, 2, 1]
    metrics = evaluate_patch_statuses(statuses, true_classes)
    # definite: (1,1) correct, (1,2) wrong, (2,2) correct, (1,1) correct
    assert metrics.ambiguity_rate == pytest.approx(1 / 5)
    assert metrics.miscoverage_rate == pytest.approx(1 / 5)
    assert metrics.accuracy == pytest.approx(3 / 4)
    assert metrics.n == 5


def test_evaluate_patch_statuses_accuracy_is_zero_when_all_ambiguous():
    metrics = evaluate_patch_statuses([AMBIGUOUS, AMBIGUOUS], [1, 2])
    assert metrics.accuracy == 0.0
    assert metrics.ambiguity_rate == 1.0
    assert metrics.miscoverage_rate == 0.0


def test_evaluate_patch_statuses_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="same length"):
        evaluate_patch_statuses([1], [1, 2])


def test_evaluate_patch_statuses_rejects_empty_input():
    with pytest.raises(ValueError, match="zero patches"):
        evaluate_patch_statuses([], [])


# --------------------------------------------------------------------------
# Vectorized path: must agree exactly with the set-based path
# --------------------------------------------------------------------------


def _sets_to_mask(pixel_sets: list[set[int]], n_classes: int) -> np.ndarray:
    mask = np.zeros((len(pixel_sets), n_classes), dtype=bool)
    for i, s in enumerate(pixel_sets):
        for c in s:
            mask[i, c] = True
    return mask


def test_prediction_mask_matches_prediction_sets_batch_exactly():
    rng = np.random.default_rng(3)
    probs = rng.dirichlet(np.ones(4), size=200)
    calibrator = ConformalCalibrator.fit(
        {c: rng.uniform(size=50) for c in range(4)}
    )
    alpha = 0.2
    quantiles = {c: calib.quantile(alpha) for c, calib in calibrator.by_class.items()}

    sets = calibrator.prediction_sets_batch(probs, alpha)
    mask = prediction_mask(hinge_scores(probs), quantiles)

    assert np.array_equal(mask, _sets_to_mask(sets, 4))


def test_evaluate_prediction_mask_matches_evaluate_prediction_sets():
    rng = np.random.default_rng(4)
    n, C = 500, 4
    mask = rng.random((n, C)) < 0.3
    true_classes = rng.integers(0, C, size=n)

    sets = [set(np.nonzero(row)[0].tolist()) for row in mask]
    from_sets = evaluate_prediction_sets(sets, true_classes.tolist())
    from_mask = evaluate_prediction_mask(mask, true_classes)

    assert from_mask.miscoverage_rate == pytest.approx(from_sets.miscoverage_rate)
    assert from_mask.ambiguity_rate == pytest.approx(from_sets.ambiguity_rate)
    assert from_mask.accuracy == pytest.approx(from_sets.accuracy)
    assert from_mask.n == from_sets.n


def test_evaluate_prediction_mask_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="same length"):
        evaluate_prediction_mask(np.zeros((3, 2), dtype=bool), np.zeros(2))


def test_evaluate_prediction_mask_rejects_empty_input():
    with pytest.raises(ValueError, match="zero predictions"):
        evaluate_prediction_mask(np.zeros((0, 2), dtype=bool), np.zeros(0))


def test_aggregate_patch_status_from_mask_matches_set_version_on_many_random_cases():
    rng = np.random.default_rng(5)
    for _ in range(200):
        n_pixels = rng.integers(1, 20)
        mask = rng.random((n_pixels, 4)) < 0.35
        sets = [set(np.nonzero(row)[0].tolist()) for row in mask]

        assert aggregate_patch_status_from_mask(mask) == aggregate_patch_status(sets)


def test_aggregate_patch_status_from_mask_rejects_empty_input():
    with pytest.raises(ValueError, match="zero pixels"):
        aggregate_patch_status_from_mask(np.zeros((0, 4), dtype=bool))


# --------------------------------------------------------------------------
# load_calibrator / checkpoint_fingerprint (scripts/calibrate_conformal.py's
# saved artifact, read back by app.analysis.Analyzer)
# --------------------------------------------------------------------------


def test_load_calibrator_returns_none_when_artifact_is_absent(tmp_path):
    assert load_calibrator(tmp_path) is None


def test_load_calibrator_round_trips_a_saved_calibration(tmp_path):
    rng = np.random.default_rng(7)
    np.savez_compressed(
        tmp_path / "conformal_calibration.npz",
        scores_1=rng.uniform(size=20).astype(np.float32),
        descriptors_1=rng.normal(size=(20, 6)).astype(np.float32),
        scores_2=rng.uniform(size=15).astype(np.float32),
        descriptors_2=rng.normal(size=(15, 6)).astype(np.float32),
    )
    loaded = load_calibrator(tmp_path)
    assert loaded is not None
    calibrator, bandwidth = loaded
    assert set(calibrator.by_class) == {1, 2}
    assert calibrator.by_class[1].n == 20
    assert calibrator.by_class[2].n == 15
    assert bandwidth > 0


def test_load_calibrator_still_works_without_a_descriptors_array():
    """A calibration built with class_descriptors=None (or a partial one) must
    still load -- ClassCalibration itself already treats missing descriptors
    as "unweighted only", not an error, and this loader must not be stricter
    than the class it is rebuilding."""
    import tempfile
    from pathlib import Path as _Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp = _Path(tmp)
        np.savez_compressed(tmp / "conformal_calibration.npz", scores_1=np.array([0.1, 0.2, 0.3]))
        loaded = load_calibrator(tmp)
        assert loaded is not None
        calibrator, _bandwidth = loaded
        assert calibrator.by_class[1].stain_descriptors is None


def test_checkpoint_fingerprint_differs_for_files_of_different_size(tmp_path):
    a = tmp_path / "a.pt"
    b = tmp_path / "b.pt"
    a.write_bytes(b"x" * 10)
    b.write_bytes(b"x" * 20)
    assert checkpoint_fingerprint(a) != checkpoint_fingerprint(b)


def test_checkpoint_fingerprint_matches_itself(tmp_path):
    path = tmp_path / "a.pt"
    path.write_bytes(b"x" * 10)
    assert checkpoint_fingerprint(path) == checkpoint_fingerprint(path)
