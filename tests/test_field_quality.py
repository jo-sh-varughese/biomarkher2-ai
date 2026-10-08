"""Edge cases the analysis must refuse to grade, and real fields it must still grade.

Every case here once produced a confident HER2 grade (or a crash) before the
field-quality gate existed (2026-10-08 probe): blank glass -> 2+ "ISH
required", a black frame -> 3+, noise -> 3+, an H&E-like image -> 2+, a
greyscale 3+ field -> 0 "ISH not indicated", an all-brown image -> crash.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.field_quality import BLOCK, CAUTION, assess, measure_image

ROOT = Path(__file__).resolve().parents[1]
rng = np.random.default_rng(42)


def _noisy(rgb, amp=4):
    return np.clip(rgb.astype(np.int16) + rng.integers(-amp, amp + 1, rgb.shape), 0, 255).astype(np.uint8)


def _hed_image(h, e, d):
    """RGB from haematoxylin / eosin / DAB concentration maps (skimage's HED space)."""
    from skimage.color import hed2rgb

    rgb = hed2rgb(np.stack([h, e, d], -1))
    return _noisy((np.clip(rgb, 0, 1) * 255).astype(np.uint8), 3)


def _her2_like(size=512, membranes=True, nuclear=False, eosin=0.0):
    """Glass with tissue: haematoxylin nuclei and, optionally, DAB membranes (HER2)
    or DAB-filled nuclei (a nuclear marker such as Ki-67)."""
    yy, xx = np.mgrid[:size, :size]
    h = np.zeros((size, size)); d = np.zeros((size, size)); e = np.full((size, size), 0.0)
    m = size // 10
    h[m:-m, m:-m] = 0.03
    e[m:-m, m:-m] = eosin
    for cy, cx in rng.integers(m + 30, size - m - 30, (size * size // 3500, 2)):
        r = np.hypot(yy - cy, xx - cx)
        if nuclear:
            d = np.maximum(d, np.where(r < 10, 0.15, 0))
        else:
            h = np.maximum(h, np.where(r < 9, 0.2, 0))
            if membranes:
                d = np.maximum(d, np.where((r > 20) & (r < 25), 0.15, 0))
    return _hed_image(h, e, d)


def _codes(verdict, level=None):
    return {r["code"] for r in verdict["reasons"] if level is None or r["level"] == level}


# ----------------------------------------------------------- things that are not a field


@pytest.mark.parametrize("name,img,code", [
    ("blank glass", np.full((512, 512, 3), 244, np.uint8), "little_tissue"),
    ("black frame", np.zeros((512, 512, 3), np.uint8), "too_dark"),
    ("uniform noise", rng.integers(0, 256, (512, 512, 3), dtype=np.uint8), "noise"),
    ("flat brown fill", np.full((512, 512, 3), (120, 70, 30), np.uint8), "graphics"),
    ("flat blue fill", np.full((512, 512, 3), (90, 100, 170), np.uint8), "graphics"),
    ("tiny crop", _her2_like(512)[:64, :64], "too_small"),
])
def test_non_fields_are_not_assessable(name, img, code):
    from app.field_quality import stained_mask

    m = measure_image(img)
    verdict = assess(m, tissue_percent=100 * float(stained_mask(img).mean()))
    assert verdict["assessable"] is False, name
    assert code in _codes(verdict, BLOCK), (name, verdict["reasons"])
    assert verdict["summary"]


def test_greyscale_field_is_refused_not_called_negative():
    grey = np.repeat(_her2_like().mean(-1, keepdims=True), 3, -1).astype(np.uint8)
    verdict = assess(measure_image(grey), tissue_percent=40)
    assert not verdict["assessable"] and "greyscale" in _codes(verdict, BLOCK)


def test_he_section_is_refused_as_wrong_stain():
    he = _her2_like(membranes=False, eosin=0.05)
    verdict = assess(measure_image(he), tissue_percent=60)
    assert not verdict["assessable"] and "not_ihc" in _codes(verdict, BLOCK)


def test_nuclear_dab_stain_is_refused_as_not_her2():
    ki = _her2_like(nuclear=True)
    m = measure_image(ki)
    assert m["nuclear_pattern"] > 0.3
    assert "nuclear_stain" in _codes(assess(m, tissue_percent=60), BLOCK)


def test_membranous_her2_pattern_is_not_mistaken_for_a_nuclear_stain():
    m = measure_image(_her2_like(membranes=True))
    verdict = assess(m, tissue_percent=60, n_cells=200, focus=0.001)
    assert "nuclear_stain" not in _codes(verdict), verdict["reasons"]
    assert verdict["assessable"], verdict["reasons"]


def test_green_marker_is_excluded_and_a_heavy_mark_refused():
    img = _her2_like()
    img[100:140, 100:300] = _noisy(np.full((40, 200, 3), (40, 160, 70), np.uint8))
    m = measure_image(img)
    assert m["artefact_mask"][120, 200] and m["foreign_fraction"] > 0.005
    assert "marker" in _codes(assess(m, tissue_percent=60, n_cells=200), CAUTION)
    heavy = img.copy()
    heavy[60:450, 60:450] = _noisy(np.full((390, 390, 3), (40, 160, 70), np.uint8))
    assert "marker" in _codes(assess(measure_image(heavy), tissue_percent=60), BLOCK)


def test_black_ink_and_deposits_are_excluded_with_a_caution():
    img = _her2_like()
    img[200:260, 200:260] = _noisy(np.full((60, 60, 3), (25, 25, 30), np.uint8))
    m = measure_image(img)
    assert m["artefact_mask"][230, 230]
    verdict = assess(m, tissue_percent=60, n_cells=200, focus=0.001, excluded_percent=2.0)
    assert {"dark_deposits", "excluded"} <= _codes(verdict, CAUTION)
    assert verdict["assessable"]


def test_too_little_tissue_too_few_cells_and_blur_block_a_grade():
    m = measure_image(_her2_like())
    assert "little_tissue" in _codes(assess(m, tissue_percent=2.0), BLOCK)
    assert "few_cells" in _codes(assess(m, tissue_percent=50, n_cells=12), BLOCK)
    assert "few_cells" in _codes(assess(m, tissue_percent=50, n_cells=60), CAUTION)
    assert "out_of_focus" in _codes(assess(m, tissue_percent=50, n_cells=200, focus=0.00005), BLOCK)


def test_non_breast_specimen_is_not_scored_by_breast_rules():
    m = measure_image(_her2_like())
    assert "not_breast" in _codes(assess(m, specimen="gastric"), BLOCK)
    assert "not_breast" not in _codes(assess(m, specimen="breast"))


def test_edge_artefact_pattern_gives_a_caution():
    from app.field_quality import edge_dab_share

    tissue = np.zeros((400, 400), bool); tissue[50:350, 50:350] = True
    dab = np.zeros((400, 400)); dab[50:60, 50:350] = 1.0; dab[50:350, 50:60] = 1.0
    share = edge_dab_share(dab, tissue)
    assert share is not None and share > 0.5
    verdict = assess(measure_image(_her2_like()), tissue_percent=60, n_cells=200, edge_share=share)
    assert "edge_artefact" in _codes(verdict, CAUTION)


# ----------------------------------------------------------- real fields must still pass


def _real(pattern, n):
    paths = sorted(ROOT.glob(pattern))
    if not paths:
        pytest.skip(f"no images for {pattern}")
    idx = np.random.default_rng(1).choice(len(paths), size=min(n, len(paths)), replace=False)
    return [np.array(Image.open(paths[i]).convert("RGB")) for i in idx]


@pytest.mark.parametrize("pattern", ["data/raw/test/class_*/*.png", "data/external/bci/IHC_test/*.png"])
def test_real_her2_fields_from_two_sites_pass_the_image_checks(pattern):
    for img in _real(pattern, 25):
        verdict = assess(measure_image(img))
        assert verdict["assessable"], verdict["reasons"]


def test_real_ki67_nuclear_stain_is_mostly_caught():
    imgs = _real("data/external/ki67/BCData/images/test/*.png", 30)
    caught = [bool({"nuclear_stain", "not_ihc"} & _codes(assess(measure_image(i)))) for i in imgs]
    assert np.mean(caught) >= 0.7


# ----------------------------------------------------------- guidance and records


def test_not_assessable_guidance_has_no_grade_and_no_ish():
    from app.guidance import recommend

    verdict = assess(measure_image(np.zeros((512, 512, 3), np.uint8)), tissue_percent=100)
    g = recommend(None, {"field_category": "3+"}, {}, quality=verdict)
    assert g["suggested_range"] == "Not assessable" and g["ish"]["level"] == "not_applicable"
    assert g["next_steps"] and "3+" not in g["ish"]["text"]


@pytest.mark.parametrize("extra,msg", [
    ({"tumour_site": "gastric or gastro-oesophageal"}, "Gastric"),
    ({"control_status": "unacceptable"}, "control"),
    ({"fixation_ok": "no"}, "falsely negative"),
    ({"artefacts": ["decalcified"]}, "falsely negative"),
    ({"artefacts": ["no invasive tumour in field"]}, "no invasive tumour"),
])
def test_review_record_refuses_unsafe_final_scores(extra, msg):
    from app.review_record import build_record

    with pytest.raises(ValueError, match=msg):
        build_record({"score": "0", "status": "final", "attest": True, **extra})
    # "cannot assess" is always allowed
    build_record({"score": "cannot assess from this field", "status": "final", "attest": True, **extra})


# ----------------------------------------------------------- decoding uploads


def _png(arr, mode=None, **save):
    buf = io.BytesIO()
    (Image.fromarray(arr, mode) if mode else Image.fromarray(arr)).save(buf, format=save.pop("format", "PNG"), **save)
    return buf.getvalue()


def test_corrupt_and_empty_uploads_give_a_clear_message():
    from app.image_io import ImageDecodeError, decode_upload

    with pytest.raises(ImageDecodeError, match="empty"):
        decode_upload(b"")
    with pytest.raises(ImageDecodeError, match="not an image"):
        decode_upload(b"this is not an image")
    with pytest.raises(ImageDecodeError):
        decode_upload(_png(np.zeros((64, 64, 3), np.uint8))[:60])


def test_sixteen_bit_transparent_cmyk_and_multipage_images_decode_sensibly():
    from app.image_io import decode_upload

    a16 = (np.linspace(0, 60000, 64 * 64).reshape(64, 64)).astype(np.uint16)
    rgb, notes = decode_upload(_png(a16))
    assert rgb.dtype == np.uint8 and rgb.max() > 200 and rgb.min() < 10 and notes

    rgba = np.zeros((32, 32, 4), np.uint8)  # fully transparent -> glass (white), not black
    rgb, notes = decode_upload(_png(rgba, "RGBA"))
    assert rgb.min() == 255 and notes

    buf = io.BytesIO(); Image.new("CMYK", (16, 16), (0, 0, 0, 0)).save(buf, format="JPEG")
    assert decode_upload(buf.getvalue())[0].shape == (16, 16, 3)

    buf = io.BytesIO()
    Image.new("RGB", (16, 16), "red").save(buf, format="TIFF", save_all=True, append_images=[Image.new("RGB", (16, 16), "blue")])
    rgb, notes = decode_upload(buf.getvalue())
    assert tuple(rgb[0, 0]) == (255, 0, 0) and any("pages" in n for n in notes)


def test_exif_rotation_is_applied():
    from app.image_io import decode_upload

    img = Image.new("RGB", (40, 20), "white")
    exif = img.getexif(); exif[0x0112] = 6  # rotate 90 degrees
    buf = io.BytesIO(); img.save(buf, format="JPEG", exif=exif)
    assert decode_upload(buf.getvalue())[0].shape[:2] == (40, 20)


def test_pixel_bomb_is_refused_before_decoding():
    from app.image_io import ImageDecodeError, decode_upload

    buf = io.BytesIO(); Image.new("L", (9000, 8000)).save(buf, format="PNG")
    with pytest.raises(ImageDecodeError, match="megapixels"):
        decode_upload(buf.getvalue())


# ----------------------------------------------------------- the crash that used to happen


def test_uniform_stain_field_no_longer_crashes_cell_detection():
    from app.cells import detect_cells_from_membranes, CellParams

    d = np.full((300, 300), 0.8)
    tissue = np.ones((300, 300), bool)
    assert detect_cells_from_membranes(d, tissue, CellParams()).max() == 0


# ----------------------------------------------------------- end to end through the analyzer


from tests.test_app import analyzer  # noqa: E402,F401  (module-scoped untrained-model fixture)


def test_analyzer_returns_no_grade_for_blank_noise_and_wrong_specimen(request):
    analyzer = request.getfixturevalue("analyzer")
    analyzer.quality_gate = True
    try:
        for img, spec in ((np.full((512, 512, 3), 244, np.uint8), "breast"),
                          (rng.integers(0, 256, (512, 512, 3), dtype=np.uint8), "breast"),
                          (_her2_like(), "gastric")):
            r = analyzer.analyze(img, patch_id="edge", specimen=spec).to_dict()
            assert r["quality"]["assessable"] is False
            assert r["guidance"]["suggested_range"] == "Not assessable"
            assert r["guidance"]["ish"]["level"] == "not_applicable"
            assert (r["cell_evidence"] or {}).get("field_category") is None
            assert not (r["ai_prescore"] or {}).get("shown")
    finally:
        analyzer.quality_gate = False


# ----------------------------------------------------------- whole slides


def test_he_whole_slide_is_not_scored(tmp_path):
    from tests.test_wsi import _StubAnalyzer
    from wsi.analysis import SlideAnalyzer, SlideSettings
    from wsi.reader import Slide

    big = _her2_like(2048, membranes=False, eosin=0.05)
    Image.fromarray(big).save(tmp_path / "he.png")
    result = SlideAnalyzer(_StubAnalyzer(), SlideSettings(max_fields=3)).run(Slide(tmp_path / "he.png", mpp_override=0.25))
    assert result["quality"]["assessable"] is False
    assert result["guidance"]["suggested_range"] == "Not assessable"
    assert result["guidance"]["ish"]["level"] == "not_applicable"
    assert any("H&E" in f for f in result["flags"])
    assert all(f["code"] == "not_ihc" for f in result["rejected_fields"])


def test_analyze_endpoint_rejects_corrupt_uploads_and_refuses_non_breast(analyzer, tmp_path):
    import base64

    from app.server import State
    from tests.portal_client import Running

    state = State(analyzer, Path("data/raw"), tmp_path / "reviews.jsonl")
    bad = "data:image/png;base64," + base64.b64encode(b"not an image at all").decode()
    good = "data:image/png;base64," + base64.b64encode(_png(_her2_like())).decode()
    analyzer.quality_gate = True
    try:
        with Running(state, role="pathologist") as srv:
            r = srv.send("POST", "/api/analyze", {"image": bad, "name": "x.png"})
            assert r.status == 400 and "not an image" in r.json["error"]
            r = srv.send("POST", "/api/analyze", {"image": good, "name": "g.png", "specimen": "gastric"})
            assert r.status == 200 and r.json["quality"]["assessable"] is False
            assert r.json["guidance"]["suggested_range"] == "Not assessable"
    finally:
        analyzer.quality_gate = False


def test_pdf_report_of_a_not_assessable_field_says_so_and_has_no_grade(analyzer):
    import pymupdf

    from app.report import build_report_pdf_bytes

    analyzer.quality_gate = True
    try:
        result = analyzer.analyze(rng.integers(0, 256, (512, 512, 3), dtype=np.uint8), patch_id="noise.png").to_dict()
    finally:
        analyzer.quality_gate = False
    text = " ".join(page.get_text() for page in pymupdf.open(stream=build_report_pdf_bytes(result), filetype="pdf"))
    assert "NOT ASSESSABLE" in text and "pixel noise" in text
    assert "IHC 3+" not in text and "IHC None" not in text
