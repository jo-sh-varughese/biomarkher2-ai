import numpy as np
import pytest

from evaluation.membrane_completeness import ComponentFeatures
from scripts import evaluate_membrane_completeness as script
from scripts.evaluate_membrane_completeness import (
    MODERATE_CLASS,
    _safe_spearman,
    correlations,
    moderate_stats,
    morphology_stats,
)


def test_safe_spearman_returns_correlation():
    result = _safe_spearman(
        [1.0, 2.0, 3.0, 4.0],
        [1.0, 3.0, 2.0, 5.0],
    )

    assert result["n"] == 4
    assert result["rho"] is not None
    assert result["p_value"] is not None


def test_safe_spearman_handles_too_few_values():
    result = _safe_spearman(
        [1.0, 2.0],
        [2.0, 3.0],
    )

    assert result["n"] == 2
    assert result["rho"] is None
    assert result["p_value"] is None


def test_safe_spearman_handles_constant_input():
    result = _safe_spearman(
        [1.0, 1.0, 1.0],
        [1.0, 2.0, 3.0],
    )

    assert result["n"] == 3
    assert result["rho"] is None
    assert result["p_value"] is None


def test_safe_spearman_constant_input_says_why_and_does_not_warn(recwarn):
    result = _safe_spearman([2.0, 2.0, 2.0, 2.0], [1.0, 2.0, 3.0, 4.0])

    assert result["reason"] == "constant input"
    assert not [w for w in recwarn if "ConstantInput" in w.category.__name__]


def _tile(*moderate_pixels):
    tile = np.ones((4, 4), dtype=np.uint8)
    for row, col in moderate_pixels:
        tile[row, col] = MODERATE_CLASS
    return tile


def test_moderate_stats_perfect_agreement():
    stats = moderate_stats(_tile((0, 0), (0, 1)), _tile((0, 0), (0, 1)))

    assert stats["moderate_iou"] == 1.0
    assert stats["moderate_present"] == 1
    assert stats["moderate_false_positive_pixels"] == 0
    assert stats["moderate_false_negative_pixels"] == 0


def test_moderate_stats_counts_both_error_directions():
    # target: (0,0) (0,1); prediction: (0,1) (0,2) -> 1 shared, 1 missed, 1 spurious
    stats = moderate_stats(_tile((0, 0), (0, 1)), _tile((0, 1), (0, 2)))

    assert stats["moderate_target_pixels"] == 2
    assert stats["moderate_predicted_pixels"] == 2
    assert stats["moderate_false_positive_pixels"] == 1
    assert stats["moderate_false_negative_pixels"] == 1
    assert stats["moderate_iou"] == pytest.approx(1 / 3)
    assert stats["moderate_false_positive_fraction"] == pytest.approx(1 / 16)
    assert stats["moderate_false_negative_fraction"] == pytest.approx(1 / 16)


def test_moderate_stats_flags_a_tile_with_no_moderate_anywhere():
    stats = moderate_stats(_tile(), _tile())

    assert stats["moderate_present"] == 0
    assert stats["moderate_iou"] == 0.0


def test_moderate_stats_tells_absent_apart_from_present_but_missed():
    # Both have IoU 0.0; only moderate_present distinguishes "nothing to find"
    # from "found nothing", which is the distinction the correlations need.
    absent = moderate_stats(_tile(), _tile())
    missed = moderate_stats(_tile((0, 0), (1, 1)), _tile())

    assert absent["moderate_iou"] == missed["moderate_iou"] == 0.0
    assert absent["moderate_present"] == 0
    assert missed["moderate_present"] == 1
    assert missed["moderate_false_negative_pixels"] == 2


def test_morphology_stats_without_components_is_all_zero():
    stats = morphology_stats([])

    assert stats == {
        "component_count": 0,
        "mean_completeness": 0.0,
        "median_completeness": 0.0,
        "mean_boundary_continuity": 0.0,
        "mean_ringness": 0.0,
    }


def test_morphology_stats_summarises_components():
    features = [
        ComponentFeatures(
            area=50, boundary_continuity=1.0, boundary_enrichment=0.9, ringness=0.5, completeness=0.4
        ),
        ComponentFeatures(
            area=30, boundary_continuity=0.5, boundary_enrichment=0.5, ringness=0.3, completeness=0.0
        ),
    ]

    stats = morphology_stats(features)

    assert stats["component_count"] == 2
    assert stats["mean_completeness"] == pytest.approx(0.2)
    assert stats["mean_boundary_continuity"] == pytest.approx(0.75)
    assert stats["mean_ringness"] == pytest.approx(0.4)


def _row(completeness, iou):
    return {
        "mean_completeness": completeness,
        "mean_ringness": completeness,
        "mean_boundary_continuity": completeness,
        "moderate_iou": iou,
        "moderate_false_positive_fraction": 1.0 - iou,
        "moderate_false_negative_fraction": iou,
    }


def test_correlations_reports_every_pair():
    rows = [_row(0.1, 0.2), _row(0.3, 0.4), _row(0.5, 0.6), _row(0.7, 0.9)]

    result = correlations(rows)

    assert set(result) == {
        "completeness_vs_moderate_iou",
        "completeness_vs_moderate_false_positive_fraction",
        "completeness_vs_moderate_false_negative_fraction",
        "ringness_vs_moderate_iou",
        "continuity_vs_moderate_iou",
    }
    assert result["completeness_vs_moderate_iou"]["rho"] == pytest.approx(1.0)
    assert result["completeness_vs_moderate_false_positive_fraction"]["rho"] == pytest.approx(-1.0)


def test_correlations_on_too_few_rows_is_none_not_an_error():
    result = correlations([_row(0.1, 0.2)])

    assert all(entry["rho"] is None for entry in result.values())


def test_main_without_a_run_config_exits_with_a_clear_message(tmp_path, monkeypatch):
    monkeypatch.setattr(script.sys, "argv", ["evaluate_membrane_completeness.py", "--run", str(tmp_path)])

    with pytest.raises(SystemExit) as raised:
        script.main()

    assert "resolved_config.yaml" in str(raised.value)
