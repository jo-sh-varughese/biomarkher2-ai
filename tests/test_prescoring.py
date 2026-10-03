"""Tests for the pre-scoring system: ISH guidance rules, cell-level evidence, report.

The guidance tests pin the ASCO/CAP algorithm (2+ -> reflex ISH required; 3+
-> not required only when nothing argues against it; 0/1+ near the 2+ boundary
-> ISH or second review) and the rule that nothing is ever a verdict.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from app.cells import CellParams, analyze_cells, classify_cell, load_cell_params, summarize
from app.guidance import recommend
from preprocessing.config import PreprocessingConfig
from preprocessing.stains import build_stain_matrix, od_to_rgb

PREP = PreprocessingConfig.from_yaml("configs/preprocessing.yaml")


def _pre(cat, probs=None, conf=0.95, borderline=False, hetero=False, runner="2+"):
    probs = probs or {g: (conf if g == cat else (1 - conf) / 3) for g in ("0", "1+", "2+", "3+")}
    return {"category": cat, "probabilities": probs, "confidence": conf, "margin_to_runner_up": 0.8,
            "runner_up": runner, "borderline": borderline,
            "heterogeneity": {"heterogeneous": hetero, "regions_by_grade": {cat: 1.0}}}


def _cells(cat, at_least_2=0.0, flags=None, ultralow=False):
    return {"field_category": cat, "percent_at_least_2plus": at_least_2, "flags": flags or [], "her2_ultralow": ultralow}


POLICY = {"site": "s", "status": "validated", "show_scores": True}


def test_2plus_always_requires_reflex_ish():
    g = recommend(_pre("2+"), _cells("2+", 30), POLICY)
    assert g["ish"]["level"] == "required"


def test_confident_concordant_3plus_does_not_need_ish_but_any_caution_does():
    assert recommend(_pre("3+"), _cells("3+", 80), POLICY)["ish"]["level"] == "not_indicated_by_ihc"
    assert recommend(_pre("3+"), _cells("1+"), POLICY)["ish"]["level"] == "recommended"            # discordant cells
    assert recommend(_pre("3+", conf=0.6), _cells("3+", 80), POLICY)["ish"]["level"] == "recommended"  # low confidence
    assert recommend(_pre("3+", hetero=True), _cells("3+", 80), POLICY)["ish"]["level"] == "recommended"


def test_1plus_near_the_2plus_boundary_gets_ish_or_second_review():
    probs = {"0": 0.05, "1+": 0.6, "2+": 0.3, "3+": 0.05}
    assert recommend(_pre("1+", probs, conf=0.6), _cells("1+"), POLICY)["ish"]["level"] == "recommended"
    g = recommend(_pre("1+"), _cells("1+"), POLICY)
    assert g["ish"]["level"] == "not_indicated_by_ihc"
    assert any("HER2-low" in s for s in g["next_steps"])


def test_ultralow_and_withheld_prescore_paths():
    g = recommend(None, _cells("0", ultralow=True), {"status": "shadow_mode"})
    assert g["basis"] == "cell evidence"
    assert any("withheld" in c for c in g["cautions"])
    assert any("ultralow" in s for s in g["next_steps"])


def test_guidance_never_states_a_verdict():
    for cat in ("0", "1+", "2+", "3+"):
        text = json.dumps(recommend(_pre(cat), _cells(cat), POLICY)).lower()
        assert "verdict" not in text and "diagnosis" not in text


def test_field_rule_follows_asco_cap_ten_percent():
    def recs(n3, n2, n1, n0):
        return ([{"category": "3+", "atypical": False, "cytoplasm_od": 0}] * n3 + [{"category": "2+", "atypical": False, "cytoplasm_od": 0}] * n2
                + [{"category": "1+", "atypical": False, "cytoplasm_od": 0}] * n1 + [{"category": "0", "atypical": False, "cytoplasm_od": 0}] * n0)
    assert summarize(recs(11, 0, 0, 89))["field_category"] == "3+"
    assert summarize(recs(5, 6, 0, 89))["field_category"] == "2+"
    assert summarize(recs(0, 0, 11, 89))["field_category"] == "1+"
    s = summarize(recs(0, 0, 5, 95))
    assert s["field_category"] == "0" and s["her2_ultralow"]
    assert any("cells detected" in f for f in summarize(recs(0, 0, 1, 9))["flags"])


def test_cell_category_depends_on_completeness_and_intensity():
    p = CellParams(membrane_faint=0.2, membrane_strong=0.8, complete_fraction=0.5, any_fraction=0.1)
    full_strong = {"sector_max": np.full(24, 1.0)}
    full_weak = {"sector_max": np.full(24, 0.35)}
    partial_weak = {"sector_max": np.r_[np.full(6, 0.3), np.zeros(18)]}
    none = {"sector_max": np.zeros(24)}
    assert classify_cell(full_strong, p, (0.25, 0.5, 0.8))["category"] == "3+"
    assert classify_cell(full_weak, p, (0.25, 0.5, 0.8))["category"] == "2+"
    assert classify_cell(partial_weak, p, (0.25, 0.5, 0.8))["category"] == "1+"
    assert classify_cell(none, p, (0.25, 0.5, 0.8))["category"] == "0"


def test_analyze_cells_finds_a_membrane_ring_on_a_rendered_cell():
    size = 256
    yy, xx = np.mgrid[:size, :size]
    r = np.hypot(yy - 128, xx - 128)
    h = np.where(r < 30, 0.9, 0.08)                               # nucleus
    d = np.where((r > 62) & (r < 74), 1.1, 0.0)                    # strong circumferential membrane
    conc = np.stack([h, d, np.zeros_like(h)], -1)
    rgb = od_to_rgb(conc @ build_stain_matrix())
    tissue = r < 90
    params = load_cell_params(None).__class__(cell_expand=70, membrane_width=6, min_nucleus_area=400,
                                               membrane_faint=0.2, membrane_strong=0.8, complete_fraction=0.5)
    out = analyze_cells(rgb, tissue, PREP.stain.thresholds(), params)
    assert out["summary"]["cells_measured"] == 1
    cell = out["cells"][0]
    assert cell["completeness"] > 0.8 and cell["category"] == "3+"


def test_calibrated_params_load_and_scale():
    p = load_cell_params("configs/cell_params.json")
    assert p.membrane_faint is not None
    half = load_cell_params("configs/cell_params.json", scale=0.5)
    assert half.cell_expand == p.cell_expand // 2 and half.min_nucleus_area < p.min_nucleus_area


def test_report_renders_with_and_without_a_shown_prescore():
    from app.report import build_report_pdf_bytes

    base = {"patch_id": "f.png", "width": 64, "height": 64, "tissue_percent": 50.0, "images": {},
            "model_percentages": {"negative": 50.0}, "baseline_percentages": {"negative": 50.0},
            "cell_evidence": {"cells_measured": 120, "percent": {"0": 50, "1+": 10, "2+": 30, "3+": 10},
                              "field_category": "2+", "rule_applied": "x", "flags": []},
            "guidance": recommend(_pre("2+"), _cells("2+", 40), POLICY), "caveats": {"a": "b"}}
    shown = dict(base, ai_prescore={"available": True, "shown": True, "site": "s", "validated": True,
                                    "prescore": dict(_pre("2+"), model={"encoder": "resnet50", "epoch": 1, "trained_on": ["x"]},
                                                     regions=[{"row": 0, "col": 0, "category": "2+", "attention": 1.0,
                                                               "tissue_fraction": 1.0, "probabilities": {"0": 0, "1+": 0, "2+": 1, "3+": 0}}])})
    withheld = dict(base, ai_prescore={"available": True, "shown": False, "site": "s", "withheld_reasons": ["not validated"]})
    for analysis in (shown, withheld):
        pdf = build_report_pdf_bytes(analysis)
        assert pdf[:4] == b"%PDF" and len(pdf) > 2000


def test_a_renamed_site_does_not_inherit_the_training_site_validation():
    """--site-name Kottayam with the default --site-validation must NOT come up validated."""
    from app.server import build_argparser, build_site_policy

    trained = build_site_policy(build_argparser().parse_args([]))
    assert trained["status"] == "validated" and trained["show_scores"]
    other = build_site_policy(build_argparser().parse_args(["--site-name", "Kottayam"]))
    assert other["status"] != "validated" and not other["show_scores"]
    assert "not for this site" in other["reasons"][0]


def test_strongly_positive_field_with_hidden_nuclei_still_yields_cells():
    """A textbook 3+ field: brown cytoplasm hides the nuclei, membranes form closed rings.

    The nucleus-first detector finds nothing there (seen on a real 3+ image, 2026-10-02);
    the membrane-first fallback must measure the cells instead of reporting 0 cells / IHC 0.
    """
    import numpy as np

    from app.cells import CellParams, analyze_cells
    from preprocessing.stains import build_stain_matrix, od_to_rgb

    size, step = 768, 64
    h = np.zeros((size, size))
    d = np.full((size, size), 0.42)                   # diffuse brown cytoplasm
    yy, xx = np.mgrid[:size, :size]
    for c0 in range(step // 2, size, step):           # pale nuclei, partly hidden by DAB
        for r0 in range(step // 2, size, step):
            nuc = np.hypot(yy - r0, xx - c0) < 12
            h[nuc] = 0.15
    memb = ((yy % step) < 5) | ((xx % step) < 5)      # closed membrane rings around every cell
    d[memb] = 0.95
    rgb = od_to_rgb(np.stack([h, d, np.zeros_like(h)], -1) @ build_stain_matrix())
    tissue = np.ones((size, size), dtype=bool)
    out = analyze_cells(rgb, tissue, (0.25, 0.5, 0.8), CellParams())
    s = out["summary"]
    assert s["detection"] == "membranes"
    assert s["cells_measured"] >= 80
    assert s["percent_at_least_1plus"] > 90 and s["field_category"] in ("2+", "3+")


def test_area_percentages_share_one_tissue_denominator():
    """Model and baseline columns are both shares of the SAME tissue mask.

    The model labels some tissue pixels "background"; before 2026-10-03 those
    were dropped from the model's denominator only, inflating every model class
    (by up to 15 points on held-out fields) under a "% of detected tissue" label.
    """
    import numpy as np

    from app.analysis import percentages

    tissue = np.zeros((10, 10), dtype=bool)
    tissue[:, :8] = True                        # 80 tissue pixels
    model = np.zeros((10, 10), dtype=np.uint8)
    model[:, :4] = 1                            # 40 negative
    model[:, 4:6] = 4                           # 20 strong; 20 tissue pixels left "background"
    p = percentages(model, tissue)
    assert p["negative"] == 50.0 and p["strong (3+)"] == 25.0
    assert abs(sum(p.values()) - 75.0) < 1e-6   # the other 25% is reported as unclassified
