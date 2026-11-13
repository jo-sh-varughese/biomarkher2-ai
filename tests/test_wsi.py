"""Tests for whole-slide analysis (wsi/): reading at physical resolution, safe
slide ids, exclusion of control cores and ink, per-slide control calibration,
the slide pipeline and its safety rules. Uses small synthetic "slides" (plain images opened through OpenSlide's
ImageSlide), so no real WSI or download is needed."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("openslide")

from preprocessing.config import PreprocessingConfig  # noqa: E402
from preprocessing.stains import build_stain_matrix, od_to_rgb  # noqa: E402
from wsi.reader import Slide, list_slides, tissue_overview_mask  # noqa: E402

PREP = PreprocessingConfig.from_yaml("configs/preprocessing.yaml")


def _synthetic_slide(path: Path, size: int = 2048) -> Path:
    """Glass with a tissue block of nuclei-like blobs and DAB membranes."""
    rng = np.random.default_rng(0)
    h = np.zeros((size, size))
    d = np.zeros((size, size))
    yy, xx = np.mgrid[:size, :size]
    margin = size // 8
    h[margin:size - margin, margin:size - margin] = 0.15
    lo, hi = margin + 40, size - margin - 40
    for cy, cx in rng.integers(lo, max(lo + 1, hi), (max(4, size * size // 28000), 2)):
        win = (slice(cy - 40, cy + 40), slice(cx - 40, cx + 40))
        rr = np.hypot(yy[win] - cy, xx[win] - cx)
        h[win] = np.maximum(h[win], np.where(rr < 14, 0.9, 0))
        d[win] = np.maximum(d[win], np.where((rr > 30) & (rr < 36), 0.7, 0))
    rgb = od_to_rgb(np.stack([h, d, np.zeros_like(h)], -1) @ build_stain_matrix())
    # A scanner always adds a little sensor noise; a perfectly flat image is what
    # the field-quality gate rejects as a drawing or screenshot.
    rgb = np.clip(rgb.astype(np.int16) + rng.integers(-3, 4, rgb.shape), 0, 255).astype(np.uint8)
    Image.fromarray(rgb).save(path)
    return path


def test_reader_reads_at_requested_resolution(tmp_path):
    s = Slide(_synthetic_slide(tmp_path / "s.png"), mpp_override=0.25)
    assert s.info.mpp == 0.25 and s.info.vendor == "image"
    assert s.read(0, 0, 1024, 1024, target_mpp=0.5).shape == (512, 512, 3)
    assert s.read(0, 0, 512, 512).shape == (512, 512, 3)
    overview, factor = s.overview(8.0)
    assert factor == pytest.approx(32, rel=0.05)
    mask = tissue_overview_mask(overview)
    assert 0.3 < mask.mean() < 0.9  # the tissue block, not the glass margin


def test_slide_ids_cannot_escape_the_slide_folder(tmp_path):
    from wsi.server_routes import SlideState, decode_id, encode_id

    (tmp_path / "slides").mkdir()
    _synthetic_slide(tmp_path / "slides" / "a.png", 256)
    (tmp_path / "secret.png").write_bytes(b"x")
    assert decode_id(encode_id("sub/a b.svs")) == "sub/a b.svs"
    state = SlideState(tmp_path / "slides", analyzer=_StubAnalyzer())
    assert state.path(encode_id("a.png")).name == "a.png"
    with pytest.raises(FileNotFoundError):
        state.path(encode_id("../secret.png"))
    assert [x["name"] for x in list_slides(tmp_path / "slides")] == ["a.png"]


def test_on_slide_control_cores_are_separated_but_tumour_nests_are_not():
    """Controls stand apart; the patient's own tumour nests sit close together."""
    from wsi.artefacts import find_control_cores

    upp = 8.0  # overview um/px
    tissue = np.zeros((1200, 2400), dtype=bool)
    yy, xx = np.mgrid[:1200, :2400]
    for cy in range(400, 900, 60):          # patient: a cluster of small round nests ~40 um apart
        for cx in range(1400, 2000, 60):
            tissue |= np.hypot(yy - cy, xx - cx) < 25
    tissue |= np.hypot(yy - 300, xx - 200) < 60   # control core: ~1 mm round, ~12 mm away
    tissue |= np.hypot(yy - 700, xx - 200) < 60
    control, cores = find_control_cores(tissue, upp)
    assert len(cores) == 2
    assert control[300, 200] and control[700, 200]
    assert not control[400:900, 1400:2000].any()  # no nest excluded
    alone = np.zeros_like(tissue)
    alone[400:900, 1400:2000] = True
    assert find_control_cores(alone, upp)[1] == []  # one piece: nothing to separate


def test_blue_ink_film_is_flagged_but_tissue_is_not():
    from wsi.artefacts import blue_cast

    glass = (233, 234, 236)
    rng = np.random.default_rng(0)
    tissue = np.full((256, 256, 3), (236, 238, 239), dtype=np.uint8)  # gaps at glass colour
    tissue[rng.random((256, 256)) < 0.6] = (120, 110, 150)            # haematoxylin-stained cells
    ink = np.clip(np.full((256, 256, 3), (200, 207, 226)) + rng.normal(0, 4, (256, 256, 3)), 0, 255).astype(np.uint8)
    assert blue_cast(tissue, glass) < 8
    assert blue_cast(ink, glass) > 15


def test_dab_stained_tumour_is_never_taken_for_ink():
    """A 3+ tumour on a scanner that clips glass to white has light-blue stroma as its palest
    pixels, so its blue cast looks like a film's; its DAB share says it is stained tissue."""
    from wsi.artefacts import DAB_TISSUE_SHARE, blue_cast, dab_share

    rng = np.random.default_rng(1)
    tumour = np.full((256, 256, 3), (196, 212, 236), dtype=np.uint8)   # light-blue stroma, no glass gaps
    tumour[rng.random((256, 256)) < 0.35] = (150, 95, 45)               # DAB-stained membranes
    ink = np.clip(np.full((256, 256, 3), (200, 207, 226)) + rng.normal(0, 4, (256, 256, 3)), 0, 255).astype(np.uint8)
    assert blue_cast(tumour, (255, 255, 255)) > 15                       # the old check alone flags it
    assert dab_share(tumour) > DAB_TISSUE_SHARE                          # ...the DAB guard keeps it
    assert dab_share(ink) < DAB_TISSUE_SHARE                             # real ink is still caught


class _StubAnalyzer:
    """What SlideAnalyzer needs from app.analysis.Analyzer, without a model."""

    def __init__(self, policy=None, engine=None):
        from app.cells import load_cell_params

        self.preprocessing = PREP
        self.cell_params = load_cell_params("configs/cell_params.json")
        self.prescore_engine = engine
        self.site_policy = policy or {"site": "test", "status": "validated", "show_scores": True, "research_mode": False,
                                      "reasons": [], "microns_per_pixel_scale": 1.0}


def test_slide_pipeline_runs_end_to_end_and_reports(tmp_path):
    from wsi.analysis import SlideAnalyzer, SlideSettings
    from wsi.report import build_slide_report_pdf_bytes

    s = Slide(_synthetic_slide(tmp_path / "s.png"), mpp_override=0.24)
    result = SlideAnalyzer(_StubAnalyzer(), SlideSettings(max_fields=3)).run(s)
    assert 1 <= len(result["fields"]) <= 3
    assert result["cell_evidence"]["cells_measured"] > 0
    assert any("not segmented" in f for f in result["flags"])  # tumour is never segmented -> said so
    assert result["tissue"]["tumour_segmented"] is False and "tumour" not in result
    assert result["ai_prescore"] is None and result["guidance"]["basis"].startswith("cell evidence")
    prim = result["primary_score"]                                 # the cell-level call is the slide's pre-score
    assert prim["source"].startswith("cell-level") and set(prim["cumulative_percent"]) == {"at_least_1plus", "at_least_2plus", "3plus"}
    assert prim["nearest_cut"]["text"] and prim["restricted_to_regions"] is False
    assert {"overview", "excluded_overlay", "grade_overlay"} <= set(result["images"])
    ds = result["cell_evidence"]["decision_support"]
    assert ds["pathway"] and ds["certainty"] and ds["qc"]          # ISH decision support at slide level
    assert result["cell_evidence"]["explanation"]["steps"]
    import json
    json.dumps(result)                                             # the API returns it as JSON
    assert build_slide_report_pdf_bytes(result)[:4] == b"%PDF"


def test_low_magnification_slides_never_get_a_prescore(tmp_path):
    from wsi.analysis import SlideAnalyzer, SlideSettings

    class _Engine:
        info = {"encoder": "x"}

    s = Slide(_synthetic_slide(tmp_path / "s.png"), mpp_override=0.92)
    result = SlideAnalyzer(_StubAnalyzer(engine=_Engine()), SlideSettings(max_fields=2)).run(s)
    assert result["ai_prescore"]["shown"] is False and "prescore" not in result["ai_prescore"]
    assert any("below ~20x" in f for f in result["flags"])
    # an unassessable slide must never read as "ISH not indicated"
    assert result["guidance"]["ish"]["level"] == "not_applicable"
    assert "Rescan" in result["guidance"]["next_steps"][0]


def test_too_few_cells_gives_no_grade_and_no_ish_suggestion(tmp_path):
    """A slide where almost every field is rejected (ink, blur) must not read as a grade plus "ISH recommended"
    from the few cells that remain (K-DISC slide 3: 57 cells in 3 of 40 fields read AI 1+, cells 2+, ISH)."""
    import dataclasses

    from wsi.analysis import SlideAnalyzer, SlideSettings
    from wsi.report import build_slide_report_pdf_bytes

    stub = _StubAnalyzer()
    stub.cell_params = dataclasses.replace(stub.cell_params, min_cells=10**6)  # more than any field holds
    s = Slide(_synthetic_slide(tmp_path / "s.png"), mpp_override=0.24)
    result = SlideAnalyzer(stub, SlideSettings(max_fields=2)).run(s)
    assert result["cell_evidence"]["cells_measured"] > 0
    assert result["flags"][0].startswith("Insufficient sample")
    assert result["quality"]["assessable"] is False
    assert result["primary_score"]["available"] is False and result["primary_score"]["category"] is None
    assert result["guidance"]["ish"]["level"] == "not_applicable"
    assert result["guidance"]["suggested_range"] == "Not assessable"
    assert build_slide_report_pdf_bytes(result)[:4] == b"%PDF"


def test_tile_route_matches_the_url_openseadragon_requests():
    """OpenSeadragon derives tile URLs from the descriptor URL: <dzi url>_files/<level>/<col>_<row>.jpeg."""
    import re

    from wsi.server_routes import encode_id, routes

    table = routes(lambda method, pattern, handler, perm, **kw: (method, pattern, handler))
    sid = encode_id("39_HER2_val.tif")
    url = f"/api/slides/{sid}/dzi_files/12/3_4.jpeg"
    hits = [h for m, p, h in table if m == "GET" and re.fullmatch(p, url)]
    assert hits == ["_slide_tile"]


# ------------------------------------------------------------ on-slide control calibration
class _ControlAnalyzer(_StubAnalyzer):
    def __init__(self, reference=None, level=None):
        super().__init__()
        self.control_reference = reference
        self.control_level = level


def _control_slide(tmp_path, dab_scale: float):
    """A slide that is entirely 'control' tissue, with a chosen DAB strength."""
    size = 2048
    rng = np.random.default_rng(1)
    h = np.full((size, size), 0.15)
    d = np.zeros((size, size))
    yy, xx = np.mgrid[:size, :size]
    for cy, cx in rng.integers(100, size - 100, (60, 2)):
        rr = np.hypot(yy - cy, xx - cx)
        h = np.maximum(h, np.where(rr < 14, 0.9, 0))
        d = np.maximum(d, np.where((rr > 24) & (rr < 34), 0.7 * dab_scale, 0))
    rgb = od_to_rgb(np.stack([h, d, np.zeros_like(h)], -1) @ build_stain_matrix())
    path = tmp_path / "ctl.png"
    Image.fromarray(rgb).save(path)
    return Slide(path, mpp_override=0.24)


def _full_control_map(slide):
    from wsi.analysis import CONTROL, OVERVIEW_MPP

    overview, factor = slide.overview(OVERVIEW_MPP)
    return np.full(overview.shape[:2], CONTROL, dtype=np.int8), factor


def test_control_is_measured_but_not_applied_unless_the_level_is_declared(tmp_path):
    from wsi.analysis import Progress, SlideAnalyzer

    slide = _control_slide(tmp_path, 1.0)
    cls, factor = _full_control_map(slide)
    reference = {"level": "3+", "p90": 0.9}
    for analyzer in (_ControlAnalyzer(reference=reference, level=None), _ControlAnalyzer(reference=None, level="3+")):
        rep, gain = SlideAnalyzer(analyzer)._control_calibration(slide, cls, factor, Progress())
        assert rep["measured"] and not rep["applied"] and gain is None
        assert "declare" in rep["reason"] or "reference" in rep["reason"]


def test_a_declared_3plus_control_gives_a_gain_that_matches_the_reference(tmp_path):
    from wsi.analysis import Progress, SlideAnalyzer

    slide = _control_slide(tmp_path, 0.6)                          # a pale run
    cls, factor = _full_control_map(slide)
    pale, _ = SlideAnalyzer(_ControlAnalyzer())._control_calibration(slide, cls, factor, Progress())
    p90 = pale["strongest_p90"]
    reference = {"level": "3+", "p90": p90 * 1.5}                  # the training site's control came out 1.5x darker
    rep, gain = SlideAnalyzer(_ControlAnalyzer(reference, "3+"))._control_calibration(slide, cls, factor, Progress())
    assert rep["applied"] and gain == pytest.approx(1.5, rel=1e-3)
    assert "x1.50" in rep["reason"]


def test_an_implausible_gain_is_refused_rather_than_applied(tmp_path):
    from wsi.analysis import Progress, SlideAnalyzer

    slide = _control_slide(tmp_path, 1.0)
    cls, factor = _full_control_map(slide)
    rep, gain = SlideAnalyzer(_ControlAnalyzer({"level": "3+", "p90": 50.0}, "3+"))._control_calibration(slide, cls, factor, Progress())
    assert gain is None and not rep["applied"] and "control itself may have failed" in rep["reason"]


def test_a_control_level_other_than_3plus_is_never_used(tmp_path):
    from wsi.analysis import Progress, SlideAnalyzer

    slide = _control_slide(tmp_path, 1.0)
    cls, factor = _full_control_map(slide)
    rep, gain = SlideAnalyzer(_ControlAnalyzer({"level": "1+", "p90": 0.4}, "1+"))._control_calibration(slide, cls, factor, Progress())
    assert gain is None and not rep["applied"]


def test_no_control_on_the_slide_means_nothing_to_measure(tmp_path):
    from wsi.analysis import Progress, SlideAnalyzer

    slide = _control_slide(tmp_path, 1.0)
    cls, factor = _full_control_map(slide)
    cls[:] = -1
    rep, gain = SlideAnalyzer(_ControlAnalyzer({"level": "3+", "p90": 0.5}, "3+"))._control_calibration(slide, cls, factor, Progress())
    assert rep["cores_found"] == 0 and gain is None and "No on-slide control" in rep["reason"]


def test_ink_is_found_without_any_model(tmp_path):
    """Blue ink / film blocks are excluded by colour alone (the check no longer needs a tumour model)."""
    from wsi.analysis import ARTEFACT, Progress, SlideAnalyzer

    size = 2048
    rgb = np.full((size, size, 3), (233, 234, 236), dtype=np.uint8)              # glass
    rng = np.random.default_rng(0)
    left = np.full((size, size // 2, 3), (236, 238, 239), dtype=np.uint8)
    left[rng.random((size, size // 2)) < 0.6] = (120, 110, 150)                   # real tissue
    rgb[:, : size // 2] = left
    rgb[:, size // 2:] = np.clip(np.full((size, size // 2, 3), (200, 207, 226)) + rng.normal(0, 4, (size, size // 2, 3)), 0, 255)
    path = tmp_path / "ink.png"
    Image.fromarray(rgb).save(path)
    slide = Slide(path, mpp_override=0.5)
    overview, factor = slide.overview(8.0)
    tissue = np.ones(overview.shape[:2], dtype=bool)
    cls = SlideAnalyzer(_StubAnalyzer())._artefact_map(slide, tissue, factor, Progress(), (233, 234, 236))
    half = cls.shape[1] // 2
    assert (cls[:, half + 2:] == ARTEFACT).mean() > 0.8       # the inked half
    assert (cls[:, : half - 2] == ARTEFACT).mean() < 0.2      # the tissue half is left alone


def test_pale_tissue_on_white_glass_is_found():
    """A scanner that clips glass to pure white shows pale stroma lighter than the old fixed
    OD cut-off (0.06) with a blue channel above 0.95; the mask must still find it, and on
    grey glass the cut-offs must stay as they were."""
    from wsi.reader import tissue_overview_mask

    rng = np.random.default_rng(2)
    white = np.full((300, 300, 3), 255, dtype=np.uint8)
    white[80:220, 80:220] = np.clip(np.array([214, 224, 243]) + rng.normal(0, 3, (140, 140, 3)), 0, 255)
    mask = tissue_overview_mask(white)
    assert mask[100:200, 100:200].mean() > 0.95 and not mask[:60].any()

    grey = np.full((300, 300, 3), (234, 235, 237), dtype=np.uint8)  # ACROBAT-like glass
    grey[80:220, 80:220] = (200, 170, 200)
    m2 = tissue_overview_mask(grey)
    assert m2[100:200, 100:200].all() and not m2[:60].any()


def test_textured_tissue_is_not_ink_but_a_smooth_film_is():
    """Blue-tinted tumour (white-glass scanner) is full of nuclei; an ink film is a smooth sheet."""
    from wsi.artefacts import INK_TEXTURE, block_texture

    rng = np.random.default_rng(3)
    film = np.clip(np.full((256, 256, 3), (196, 200, 228)) + rng.normal(0, 1.5, (256, 256, 3)), 0, 255).astype(np.uint8)
    tissue = np.full((256, 256, 3), (200, 214, 238), dtype=np.uint8)
    ys, xs = rng.integers(0, 252, 900), rng.integers(0, 252, 900)
    for y, x in zip(ys, xs):  # ~4 px nuclei
        tissue[y:y + 4, x:x + 4] = (110, 130, 185)
    assert block_texture(film) < INK_TEXTURE < block_texture(tissue)


def test_fields_stay_inside_pathologist_marked_regions():
    """With a marked tumour region, every field lies inside it, and the edge buffer is measured from the
    tissue edge, not from the region's own border (a small region must not lose its rim)."""
    from types import SimpleNamespace

    from wsi.analysis import SlideAnalyzer, SlideSettings

    usable = np.zeros((400, 400), dtype=bool)
    usable[20:380, 20:380] = True
    roi = np.zeros_like(usable)
    roi[150:250, 150:250] = True
    slide = SimpleNamespace(info=SimpleNamespace(mpp=None))
    sa = SlideAnalyzer(_StubAnalyzer(), SlideSettings(max_fields=40))
    fields, fo = sa._choose_fields(usable & roi, 8.0, slide, None, edge_from=usable)
    assert fields
    assert all(roi[r:r + fo, c:c + fo].mean() >= 0.5 for _, r, c in fields)


def test_primary_score_states_the_call_and_its_distance_from_the_cut_off():
    from wsi.analysis import primary_score

    cells = {"cells_measured": 3424, "percent": {"0": 96.5, "1+": 2.5, "2+": 0.7, "3+": 0.2},
             "percent_at_least_1plus": 3.4, "percent_at_least_2plus": 0.9, "field_category": "0"}
    p = primary_score(cells, {"category": "0"}, [], 100)
    assert p["available"] and p["category"] == "0" and p["agrees_with_ai"] is True
    assert p["cumulative_percent"] == {"at_least_1plus": 3.4, "at_least_2plus": 0.9, "3plus": 0.2}
    assert p["nearest_cut"]["grade"] == "1+" and p["nearest_cut"]["gap_points"] == -6.6
    assert any("automatically" in r for r in p["review"])          # no regions marked -> said so

    border = dict(cells, percent_at_least_1plus=11.0, field_category="1+")
    p = primary_score(border, {"category": "0"}, [{"x": 0, "y": 0, "w": 1, "h": 1}], 100)
    assert p["category"] == "1+" and p["agrees_with_ai"] is False
    assert any("within 3 points" in r for r in p["review"]) and any("differs" in r for r in p["review"])

    assert primary_score(dict(cells, cells_measured=20), None, [], 100)["available"] is False  # too few cells


def test_a_diluted_2plus_focus_is_never_told_ish_not_indicated():
    # HER2match 025 (a 2+ slide): 1.4% of all cells >=2+, but 4 of 40 fields are 2+/3+ on their own
    from app.guidance import recommend
    from wsi.analysis import focal_high_fields, primary_score

    fields = ([{"index": i, "cell_category": "0", "cells": 300, "cells_at_least_2plus_pct": 0.0} for i in range(36)]
              + [{"index": 36, "cell_category": "2+", "cells": 45, "cells_at_least_2plus_pct": 40.0},   # small but clearly 2+
                 {"index": 37, "cell_category": "3+", "cells": 49, "cells_at_least_2plus_pct": 60.0},
                 {"index": 38, "cell_category": "2+", "cells": 22, "cells_at_least_2plus_pct": 13.6},   # 3 of 22: not sure
                 {"index": 39, "cell_category": "1+", "cells": 300, "cells_at_least_2plus_pct": 4.0}])
    focal = focal_high_fields(fields)
    assert [f["index"] for f in focal] == [36, 37]

    cells = {"cells_measured": 9000, "percent": {"0": 94.8, "1+": 3.8, "2+": 0.9, "3+": 0.5},
             "percent_at_least_1plus": 5.2, "percent_at_least_2plus": 1.4, "field_category": "0", "flags": []}
    p = primary_score(cells, {"category": "0"}, [], 100, focal=focal)
    assert p["category"] == "0"                                      # the grade itself is not forced
    assert len(p["focal_2plus_fields"]) == 2 and any("diluted" in r for r in p["review"])

    policy = {"status": "shadow_mode"}
    assert recommend(None, cells, policy, cells_primary=True)["ish"]["level"] == "not_indicated_by_ihc"
    g = recommend(None, cells, policy, cells_primary=True, focal_2plus=len(focal))
    assert g["ish"]["level"] == "recommended" and "2+/3+ field" in g["ish"]["text"]


def test_no_focal_fields_on_a_clean_negative_slide():
    from wsi.analysis import focal_high_fields

    fields = [{"index": i, "cell_category": c, "cells": 300, "cells_at_least_2plus_pct": 1.0}
              for i, c in enumerate(["0"] * 35 + ["1+"] * 5)]
    assert focal_high_fields(fields) == []


def test_field_scoring_reads_bounded_tiles_however_wide_the_tissue():
    """Field selection once read the tissue in bands as wide as the whole section; a wide K-DISC
    slide needed several GB per band and the server was killed on an 8 GB VM (2026-11-11)."""
    from types import SimpleNamespace

    from wsi.analysis import SELECT_MPP, SELECT_TILE_PX, SlideAnalyzer

    reads = []

    class WideSlide:
        info = SimpleNamespace(mpp=0.286)

        def read(self, x, y, w, h, target_mpp=None):
            s = self.info.mpp / target_mpp
            out = (max(1, int(round(h * s))), max(1, int(round(w * s))))
            reads.append(out)
            return np.full(out + (3,), 200, dtype=np.uint8)

    factor, fo = 8.0 / 0.286, 31  # overview px -> level-0 px; one 1024 px field at 0.24 um/px in overview px
    # 4 rows x 150 columns of candidate fields: a section ~4,650 overview px (~37 mm) wide.
    cands = [(0.0, r * fo, c * fo) for r in range(4) for c in range(150)]
    scores = SlideAnalyzer._field_scores(WideSlide(), cands, fo, factor)

    assert scores.shape == (len(cands),)
    scale = factor * 0.286 / SELECT_MPP
    bound = SELECT_TILE_PX + 4 * fo * scale  # one tile plus a field and its context margin on each side
    assert max(max(h, w) for h, w in reads) <= bound
