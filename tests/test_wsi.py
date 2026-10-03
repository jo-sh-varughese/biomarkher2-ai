"""Tests for whole-slide analysis (wsi/): reading at physical resolution, safe
slide ids, the haematoxylin-only transform, the slide pipeline and its safety
rules. Uses small synthetic "slides" (plain images opened through OpenSlide's
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


def test_haematoxylin_image_ignores_dab():
    from wsi.tumour import haematoxylin_image

    h = np.full((64, 64), 0.5)
    h[:, :32] = 0.1
    with_dab = od_to_rgb(np.stack([h, np.full((64, 64), 0.8), np.zeros_like(h)], -1) @ build_stain_matrix())
    without = od_to_rgb(np.stack([h, np.zeros((64, 64)), np.zeros_like(h)], -1) @ build_stain_matrix())
    a = haematoxylin_image(with_dab, "ihc").astype(int)
    b = haematoxylin_image(without, "ihc").astype(int)
    assert np.abs(a - b).mean() < 6           # DAB does not change what the segmenter sees
    assert a[:, 40:].mean() < a[:, :20].mean()  # haematoxylin structure is kept


def test_grey_cast_scan_is_not_rendered_as_haematoxylin_everywhere():
    """A dim/grey scan (seen in BCI) must not turn into a flat purple field."""
    from wsi.tumour import haematoxylin_image

    h = np.zeros((64, 64))
    h[20:30, 20:30] = 0.8  # one nucleus on clear background
    clean = od_to_rgb(np.stack([h, np.zeros_like(h), np.zeros_like(h)], -1) @ build_stain_matrix())
    grey = (clean.astype(float) * 0.72).astype(np.uint8)  # same slide, 28% less light
    a = haematoxylin_image(clean, "ihc").astype(int)
    b = haematoxylin_image(grey, "ihc").astype(int)
    assert np.abs(a - b).mean() < 6
    assert b[:10, :10].mean() > 235  # background stays white


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
    result = SlideAnalyzer(_StubAnalyzer(), None, SlideSettings(max_fields=3)).run(s)
    assert 1 <= len(result["fields"]) <= 3
    assert result["cell_evidence"]["cells_measured"] > 0
    assert any("not segmented" in f for f in result["flags"])  # no tumour model -> said so
    assert result["ai_prescore"] is None and result["guidance"]["basis"] == "cell evidence"
    assert {"overview", "tumour_overlay", "grade_overlay"} <= set(result["images"])
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
    result = SlideAnalyzer(_StubAnalyzer(engine=_Engine()), None, SlideSettings(max_fields=2)).run(s)
    assert result["ai_prescore"]["shown"] is False and "prescore" not in result["ai_prescore"]
    assert any("below ~20x" in f for f in result["flags"])
    # an unassessable slide must never read as "ISH not indicated"
    assert result["guidance"]["ish"]["level"] == "not_applicable"
    assert "Rescan" in result["guidance"]["next_steps"][0]


def test_tile_route_matches_the_url_openseadragon_requests():
    """OpenSeadragon derives tile URLs from the descriptor URL: <dzi url>_files/<level>/<col>_<row>.jpeg."""
    import re

    from wsi.server_routes import encode_id, routes

    table = routes(lambda method, pattern, handler, perm: (method, pattern, handler))
    sid = encode_id("39_HER2_val.tif")
    url = f"/api/slides/{sid}/dzi_files/12/3_4.jpeg"
    hits = [h for m, p, h in table if m == "GET" and re.fullmatch(p, url)]
    assert hits == ["_slide_tile"]
