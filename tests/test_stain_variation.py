"""Tests for the cross-group stain-variation report (Objective 1)."""

from __future__ import annotations

import numpy as np
import pytest

from evaluation.stain_variation import build_variation_report, compute_group_stats


def test_compute_group_stats_reports_mean_and_std_per_group():
    descriptors = {
        "group_a": np.array([[1.0, 0, 0, 0, 1.0, 0], [1.1, 0, 0, 0, 0.9, 0]]),
        "group_b": np.array([[-1.0, 0, 0, 0, -1.0, 0]]),
    }
    stats = compute_group_stats(descriptors)
    by_name = {s.group: s for s in stats}
    assert set(by_name) == {"group_a", "group_b"}
    assert by_name["group_a"].n_patches == 2
    assert by_name["group_b"].n_patches == 1
    np.testing.assert_allclose(by_name["group_a"].mean_descriptor, [1.05, 0, 0, 0, 0.95, 0])


def test_compute_group_stats_rejects_an_empty_group():
    with pytest.raises(ValueError, match="no descriptors"):
        compute_group_stats({"empty": np.zeros((0, 6))})


def test_build_variation_report_requires_at_least_two_groups():
    with pytest.raises(ValueError, match="at least two groups"):
        build_variation_report({"only_one": np.zeros((3, 6))})


def test_build_variation_report_flags_clear_between_group_separation():
    rng = np.random.default_rng(0)
    tight_a = np.array([1.0, 0, 0, 0, 1.0, 0]) + rng.normal(scale=0.01, size=(30, 6))
    tight_b = np.array([-1.0, 0, 0, 0, -1.0, 0]) + rng.normal(scale=0.01, size=(30, 6))
    report = build_variation_report({"a": tight_a, "b": tight_b})

    assert report.between_group_mean_distance > report.within_group_mean_std_norm
    summary = report.summary()
    assert summary["variation_exceeds_noise"] is True
    assert summary["what_group_means"].startswith("A provenance group")
    assert "b" in summary["between_group_distances"]["a"]


def test_build_variation_report_does_not_flag_pure_noise_as_variation():
    rng = np.random.default_rng(1)
    # Both groups drawn from the SAME distribution -- any "between-group"
    # distance here is noise, not real variation.
    a = rng.normal(scale=1.0, size=(50, 6))
    b = rng.normal(scale=1.0, size=(50, 6))
    report = build_variation_report({"a": a, "b": b})
    assert report.summary()["variation_exceeds_noise"] is False


def test_write_json_round_trips_the_summary(tmp_path):
    import json

    a = np.array([[1.0, 0, 0, 0, 1.0, 0]] * 5)
    b = np.array([[-1.0, 0, 0, 0, -1.0, 0]] * 5)
    report = build_variation_report({"a": a, "b": b})

    path = tmp_path / "stain_variation.json"
    report.write_json(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["n_groups"] == 2
    assert payload == report.summary()
