"""Cross-institution conformal prediction (evaluation/cross_site_conformal.py) and the
per-site prediction sets the portal shows (app/prescore.prediction_set)."""

from __future__ import annotations

import json

import numpy as np

from evaluation.cross_site_conformal import (domain_weights, lac_scores, local_calibration, prediction_sets,
                                             weighted_threshold)


def _probs(labels, rng, sharp=4.0):
    logits = rng.normal(0, 1, (len(labels), 4))
    logits[np.arange(len(labels)), labels] += sharp
    e = np.exp(logits)
    return e / e.sum(1, keepdims=True)


def test_unweighted_split_conformal_covers_exchangeable_data():
    rng = np.random.default_rng(0)
    cal_y, test_y = rng.integers(0, 4, 600), rng.integers(0, 4, 3000)
    cal_p, test_p = _probs(cal_y, rng, 1.5), _probs(test_y, rng, 1.5)
    q = weighted_threshold(lac_scores(cal_p, cal_y), np.ones(600), 1.0, 0.1)
    sets = prediction_sets(test_p, np.full(3000, q))
    assert 0.88 <= sets[np.arange(3000), test_y].mean() <= 0.93


def test_weights_are_flat_without_shift_and_extreme_with_separable_domains():
    rng = np.random.default_rng(1)
    same_a, same_b = rng.normal(0, 1, (300, 3)), rng.normal(0, 1, (300, 3))
    _, _, auc = domain_weights(same_a, same_b)
    assert auc < 0.6
    shifted = rng.normal(5, 1, (300, 3))
    cw, tw, auc = domain_weights(same_a, shifted)
    assert auc > 0.99 and tw.mean() > 10 * cw.mean()


def test_weighted_threshold_is_infinite_when_calibration_carries_no_mass():
    assert weighted_threshold(np.array([0.1, 0.2]), np.array([1e-6, 1e-6]), 10.0, 0.1) == float("inf")


def test_local_calibration_restores_coverage_at_a_shifted_site():
    rng = np.random.default_rng(2)
    y = rng.integers(0, 4, 400)
    p = _probs(y, rng, 0.8)                      # a weak model at the new site
    res = local_calibration(p, y, ks=(40,), alphas=(0.1,), repeats=30)
    assert res["40"]["0.1"]["local_only"]["coverage_mean"] >= 0.87


def test_prediction_set_is_only_shown_for_the_site_it_was_calibrated_at(tmp_path):
    from app.prescore import prediction_set

    (tmp_path / "prescore_sets.json").write_text(json.dumps(
        {"site": "Site A", "n_cases": 100, "thresholds": {"0.05": 0.7, "0.1": 0.4, "0.2": 0.1}}), encoding="utf-8")
    probs = {"0": 0.02, "1+": 0.03, "2+": 0.65, "3+": 0.30}
    here = prediction_set(probs, tmp_path, "Site A")
    assert here["available"] and here["grades"] == ["2+"] and here["coverage"] == 0.9
    elsewhere = prediction_set(probs, tmp_path, "Site B")
    assert not elsewhere["available"] and "not for this site" in elsewhere["reason"]
    assert not prediction_set(probs, tmp_path / "missing", "Site A")["available"]
