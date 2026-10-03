"""ISH decision support (app/decision.py): the statistics and the clinical rules."""

from __future__ import annotations

from app.decision import counterfactuals, wilson


def test_wilson_interval_matches_known_values():
    lo, hi = wilson(0, 26)
    assert lo == 0.0 and 12 < hi < 14          # 0 of 26 cannot exclude ~13%
    lo, hi = wilson(17, 22)
    assert 55 < lo < 58 and 89 < hi < 91


def test_counterfactual_counts_are_exact():
    summary = {"cells_measured": 53, "field_category": "2+",
               "counts": {"0": 19, "1+": 16, "2+": 18, "3+": 0}}
    lines = counterfactuals(summary)
    assert lines[0].startswith("To reach 3+, 6 more cells")      # more than 5 of 53 needed
    assert lines[1].startswith("To fall to 1+, 13 of the 18")    # at most 5 may stay complete


def _summary(n, c3=0, c2=0, c1=0):
    return {"cells_measured": n, "field_category": "3+" if c3 / n > .1 else "2+" if (c3 + c2) / n > .1 else
            "1+" if (c3 + c2 + c1) / n > .1 else "0",
            "counts": {"3+": c3, "2+": c2, "1+": c1, "0": n - c3 - c2 - c1}, "flags": []}


def _decide(summary, prescore=None):
    import numpy as np

    from app.cells import CellParams
    from app.decision import decision_support

    rgb = np.full((64, 64, 3), 200, np.uint8)
    tissue = np.ones((64, 64), bool)
    return decision_support(rgb, tissue, [], summary, CellParams(), (0.25, 0.5, 0.8), prescore, None)


def test_a_clear_zero_with_few_cells_is_not_sent_for_ish():
    """0 of 26 complete membranes: the interval reaches 13% only because few cells were counted."""
    d = _decide(_summary(26, c1=2))
    assert not d["near_2plus"]
    assert not any("cut-off" in e["text"] for e in d["evidence_for_ish"])


def test_a_share_at_the_cut_off_is_flagged_near_2plus():
    d = _decide(_summary(46, c2=4, c1=20))   # 8.7% complete membranes, interval spans 10%
    assert d["near_2plus"]


def test_two_plus_is_always_decisive_for_ish():
    d = _decide(_summary(200, c2=60, c1=60), prescore={"category": "2+", "runner_up": "1+", "confidence": 0.8,
                                                      "borderline": False, "regions": []})
    assert any(e["weight"] == "decisive" for e in d["evidence_for_ish"])
    assert [s["grade"] for s in d["pathway"] if s["taken"]] == ["2+"]


def test_payload_never_carries_a_verdict_key():
    import json

    d = _decide(_summary(120, c3=40))
    assert '"verdict"' not in json.dumps(d)
