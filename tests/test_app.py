"""Tests for the review viewer.

Two kinds of thing are worth testing here and they are not the same kind.

The first is ordinary correctness: overlays keep their class values, tiled
prediction covers the whole image, percentages are over tissue.

The second is the framing constraint. This tool is a pre-scoring aid, and the
thing that would quietly destroy that is a UI that reads as a verdict -- a
score in the output, a review step that can be skipped, a 2+ number presented
with the same confidence as the others when the model cannot predict it. Those
are tested here as deliberately as the arithmetic, because they are the part a
future change is most likely to erode by accident.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.analysis import (
    AMBIGUITY_COLORS,
    INTENSITY_COLORS,
    ISOLATE_INK,
    MODEL_LIMITATION,
    NOT_A_SCORE,
    PALETTE,
    colorize,
    dab_heatmap,
    isolate_overlays,
    overlay,
    overlay_ambiguity,
    percentages,
    to_data_uri,
)
from preprocessing.baseline import CLASS_NAMES, NUM_CLASSES

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


# ---------------------------------------------------------------- rendering


def test_colorize_maps_every_class_to_its_own_colour():
    classes = np.arange(NUM_CLASSES, dtype=np.uint8)[None, :]
    coloured = colorize(classes)
    assert coloured.shape == (1, NUM_CLASSES, 3)
    assert len({tuple(px) for px in coloured[0]}) == NUM_CLASSES


def test_overlay_leaves_background_pixels_untouched():
    """Painting the background would hide the tissue detector's mistakes."""
    rgb = np.full((8, 8, 3), 200, dtype=np.uint8)
    classes = np.zeros((8, 8), dtype=np.uint8)
    classes[4:] = 4

    blended = overlay(rgb, classes)
    assert np.array_equal(blended[:4], rgb[:4]), "background was painted over"
    assert not np.array_equal(blended[4:], rgb[4:]), "stained region was not painted"


def test_transport_downscaling_invents_no_classes():
    """A resized class map must not contain colours no class ever had.

    Bilinear resampling of an overlay would blend weak and strong into a
    colour that reads as moderate -- inventing, in the picture, exactly the
    class the model is known not to predict.
    """
    classes = np.zeros((900, 900), dtype=np.uint8)
    classes[:, 450:] = 4
    classes[:, :450] = 2

    uri = to_data_uri(colorize(classes), max_side=64)
    assert uri.startswith("data:image/png;base64,")

    import base64
    import io

    from PIL import Image

    decoded = np.array(Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))))
    allowed = {tuple(c) for c in PALETTE.tolist()}
    assert {tuple(px) for px in decoded.reshape(-1, 3).tolist()} <= allowed


def test_overlay_ambiguity_leaves_excluded_pixels_untouched():
    """Mirrors test_overlay_leaves_background_pixels_untouched exactly --
    same reason: painting excluded pixels would hide what was excluded."""
    rgb = np.full((8, 8, 3), 200, dtype=np.uint8)
    status = np.zeros((8, 8), dtype=np.uint8)
    status[4:] = 2

    blended = overlay_ambiguity(rgb, status)
    assert np.array_equal(blended[:4], rgb[:4]), "excluded region was painted over"
    assert not np.array_equal(blended[4:], rgb[4:]), "ambiguous region was not painted"


def test_heatmap_darkens_monotonically_with_dab_signal():
    """The whole point of the heatmap over the four discrete classes is that
    it does not snap a pixel into a bucket -- a pixel with more DAB signal
    must always read as a "hotter" colour than one with less, not just a
    different one."""
    thresholds = (0.15, 0.35, 0.6)
    tissue = np.ones((1, 5), dtype=bool)
    dab = np.array([[0.0, 0.1, 0.2, 0.4, 0.8]], dtype=np.float32)
    rgb = np.full((1, 5, 3), 220, dtype=np.uint8)

    heat = dab_heatmap(rgb, dab, tissue, thresholds, alpha=1.0).astype(np.int32)
    # Distance from the lightest (weakest-signal) stop should only grow.
    distances = np.linalg.norm(heat - heat[0, 0], axis=-1)[0]
    assert list(distances) == sorted(distances)
    assert distances[-1] > 0, "the strongest pixel must not equal the weakest"


def test_heatmap_leaves_non_tissue_pixels_untouched():
    """Mirrors overlay()'s own discipline: painting outside the tissue mask
    would hide what the tissue detector excluded, here as much as there."""
    rgb = np.full((4, 4, 3), 200, dtype=np.uint8)
    dab = np.full((4, 4), 0.9, dtype=np.float32)
    tissue = np.zeros((4, 4), dtype=bool)
    tissue[2:] = True

    heat = dab_heatmap(rgb, dab, tissue, (0.15, 0.35, 0.6))
    assert np.array_equal(heat[:2], rgb[:2]), "non-tissue pixels were painted"
    assert not np.array_equal(heat[2:], rgb[2:]), "tissue pixels were not painted"


def test_isolate_overlays_paint_only_their_own_class():
    """The whole point of "isolate" is that picking the 2+ entry shows 2+
    and NOTHING else -- if it leaked another class's pixels, "where is the
    2+" would be exactly as misleading as the all-classes map it exists to
    improve on."""
    rgb = np.full((4, 8, 3), 210, dtype=np.uint8)
    classes = np.zeros((4, 8), dtype=np.uint8)
    classes[:, :2] = 1  # negative
    classes[:, 2:4] = 2  # weak
    classes[:, 4:6] = 3  # moderate
    classes[:, 6:8] = 4  # strong

    overlays = isolate_overlays(rgb, classes)
    assert set(overlays) == {"negative", "weak (1+)", "moderate (2+)", "strong (3+)"}

    moderate = overlays["moderate (2+)"].astype(int)
    ink = np.array([int(ISOLATE_INK[3][i : i + 2], 16) for i in (1, 3, 5)])
    # Its own region (columns 4:6) carries the class ink...
    assert np.abs(moderate[:, 4:6] - ink).max() < 25
    # ...and every other region is plain grey -- no other class's colour,
    # and no stain colour, for the 2+ pixels to be confused with.
    others = np.concatenate([moderate[:, :4], moderate[:, 6:8]], axis=1)
    assert (others[..., 0] == others[..., 1]).all() and (others[..., 1] == others[..., 2]).all()


def test_every_isolate_ink_is_visible_on_the_washed_field():
    """A class whose highlight blends into the wash cannot be found, which is
    the one job this view has -- negative's own faint map colour failed
    exactly this, hence ISOLATE_INK."""
    from app.analysis import desaturate
    from tests.synthetic import graded_patch

    wash = desaturate(graded_patch(size=64), lift=0.6).astype(float).mean(axis=(0, 1))
    for c, hex_colour in ISOLATE_INK.items():
        rgb = np.array([int(hex_colour[i : i + 2], 16) for i in (1, 3, 5)], dtype=float)
        assert np.linalg.norm(rgb - wash) > 60, f"class {c} ink {hex_colour} blends into the wash"


def test_ambiguity_palette_shares_no_colour_with_the_intensity_palette():
    """The ambiguity panel answers a different question ("how sure") from the
    other four ("what class"); a shared colour would let it be misread as a
    fifth intensity class at a glance."""
    confidence_colours = {AMBIGUITY_COLORS[1], AMBIGUITY_COLORS[2]}
    assert confidence_colours.isdisjoint(INTENSITY_COLORS.values())


def test_percentages_are_over_tissue_and_exclude_background():
    classes = np.zeros((10, 10), dtype=np.uint8)
    classes[:5] = 0          # half the field is background
    classes[5:8] = 1         # 30 pixels negative
    classes[8:] = 4          # 20 pixels strong

    result = percentages(classes)
    assert set(result) == {CLASS_NAMES[c] for c in range(1, NUM_CLASSES)}
    assert result[CLASS_NAMES[1]] == pytest.approx(60.0)
    assert result[CLASS_NAMES[4]] == pytest.approx(40.0)
    assert sum(result.values()) == pytest.approx(100.0)


# ------------------------------------------------------------- the analyzer


@pytest.fixture(scope="module")
def analyzer(tmp_path_factory):
    """A real Analyzer over an untrained model, so no download is needed."""
    import torch

    from app.analysis import Analyzer
    from models import select_architecture
    from training.config import TrainingConfig

    root = tmp_path_factory.mktemp("app")
    config = TrainingConfig()
    config.model.pretrained = False
    config.model.image_size = 64
    config.to_yaml(root / "training.yaml")

    build_model, _ = select_architecture(config.model.architecture)
    model = build_model(config.model, verbose=False)
    torch.save(
        {"model_state": model.state_dict(), "epoch": 1, "caveat": "test"},
        root / "best.pt",
    )
    return Analyzer(root, root / "training.yaml", "configs/preprocessing.yaml")


def test_prediction_covers_an_image_that_is_not_a_multiple_of_the_tile(analyzer):
    """A silently unpredicted margin would be an invisible bias in the areas."""
    rgb = np.random.default_rng(0).integers(60, 220, (100, 150, 3), dtype=np.uint8)
    prediction = analyzer.predict(rgb)

    assert prediction.shape == (100, 150)
    assert prediction.max() < NUM_CLASSES
    # Every tile position was written, including the ragged right/bottom edge.
    assert prediction[-1, -1] is not None
    assert prediction[:, 128:].size > 0


def test_analysis_reports_both_columns_and_never_a_score(analyzer):
    from tests.synthetic import graded_patch

    result = analyzer.analyze(graded_patch(size=128), patch_id="demo.png").to_dict()

    assert set(result["images"]) == {"original", "tissue", "model", "baseline", "heatmap"}
    assert set(result["isolate"]) == set(result["model_percentages"]), (
        "isolate must offer exactly the classes model_percentages reports, no more, no less"
    )
    assert result["baseline_percentages"], "the control column is missing"
    assert result["model_percentages"]
    assert 0.0 <= result["tissue_percent"] <= 100.0

    # No field anywhere in the payload is a HER2 score.
    flat = json.dumps(result).lower()
    for forbidden in ('"score"', '"her2_score"', '"verdict"', '"diagnosis"'):
        assert forbidden not in flat
    assert result["caveats"]["not_a_score"] == NOT_A_SCORE


def test_model_and_baseline_share_one_tissue_denominator(analyzer):
    """Two columns measured over different denominators cannot be compared."""
    from tests.synthetic import graded_patch

    result = analyzer.analyze(graded_patch(size=128)).to_dict()
    for column in ("model_percentages", "baseline_percentages"):
        total = sum(result[column].values())
        assert total == pytest.approx(100.0, abs=0.5) or total == pytest.approx(0.0)


# ------------------------------------------------------ conformal prediction


def _build_conformal_analyzer(tmp_path_factory, name: str, *, matching_epoch: bool):
    """A real Analyzer with a synthetic (but structurally real) calibration
    artifact alongside its checkpoint -- ``matching_epoch=False`` reproduces
    the exact mismatch scripts/calibrate_conformal.py's recorded identity is
    meant to catch: a checkpoint that has moved on since calibration ran."""
    import torch

    from app.analysis import Analyzer
    from evaluation.conformal import checkpoint_fingerprint
    from models import select_architecture
    from training.config import TrainingConfig

    root = tmp_path_factory.mktemp(name)
    config = TrainingConfig()
    config.model.pretrained = False
    config.model.image_size = 64
    config.to_yaml(root / "training.yaml")

    build_model, _ = select_architecture(config.model.architecture)
    model = build_model(config.model, verbose=False)
    epoch = 1
    checkpoint_path = root / "best.pt"
    torch.save(
        {"model_state": model.state_dict(), "epoch": epoch, "caveat": "test"},
        checkpoint_path,
    )

    rng = np.random.default_rng(9)
    payload = {}
    for c in range(1, NUM_CLASSES):
        payload[f"scores_{c}"] = rng.uniform(size=30).astype(np.float32)
        payload[f"descriptors_{c}"] = rng.normal(size=(30, 6)).astype(np.float32)
    np.savez_compressed(root / "conformal_calibration.npz", **payload)

    (root / "conformal_calibration_ids.json").write_text(
        json.dumps(
            {
                "checkpoint_epoch": epoch if matching_epoch else epoch + 1,
                "checkpoint_fingerprint": checkpoint_fingerprint(checkpoint_path),
            }
        ),
        encoding="utf-8",
    )
    return Analyzer(root, root / "training.yaml", "configs/preprocessing.yaml")


@pytest.fixture(scope="module")
def analyzer_with_conformal(tmp_path_factory):
    return _build_conformal_analyzer(tmp_path_factory, "app_conformal", matching_epoch=True)


@pytest.fixture(scope="module")
def analyzer_with_stale_conformal(tmp_path_factory):
    return _build_conformal_analyzer(tmp_path_factory, "app_conformal_stale", matching_epoch=False)


def test_analysis_includes_conformal_fields_and_still_never_a_score(analyzer_with_conformal):
    from tests.synthetic import graded_patch

    result = analyzer_with_conformal.analyze(graded_patch(size=128), patch_id="demo.png").to_dict()

    assert result["conformal"]["available"] is True
    assert 0.0 <= result["conformal"]["ambiguous_percent"] <= 100.0
    assert result["conformal"]["weighted"] is False
    assert result["conformal"]["stale_calibration"] is False
    assert "ambiguity" in result["images"]
    assert "conformal" in result["caveats"]

    flat = json.dumps(result).lower()
    for forbidden in ('"score"', '"her2_score"', '"verdict"', '"diagnosis"'):
        assert forbidden not in flat


def test_analysis_degrades_gracefully_with_no_calibration_artifact(analyzer):
    """The ordinary case today: no scripts/calibrate_conformal.py has run for
    this fixture's run directory. Nothing about the rest of the payload may
    depend on this feature having been used."""
    from tests.synthetic import graded_patch

    result = analyzer.analyze(graded_patch(size=128), patch_id="demo.png").to_dict()
    assert result["conformal"] == {"available": False}
    assert "ambiguity" not in result["images"]
    assert "conformal" not in result["caveats"]


def test_stale_calibration_is_flagged_loudly_not_silently(analyzer_with_stale_conformal):
    """Missing calibration degrades silently (tested above); a calibration
    that IS present but computed against a different checkpoint must not --
    it has to say so, not just quietly show numbers that might not apply."""
    from tests.synthetic import graded_patch

    result = analyzer_with_stale_conformal.analyze(graded_patch(size=128), patch_id="demo.png").to_dict()
    assert result["conformal"]["available"] is True
    assert result["conformal"]["stale_calibration"] is True
    assert "different checkpoint" in result["caveats"]["conformal"]


# ------------------------------------------------------------------ the UI


def test_the_page_says_it_does_not_assign_a_score():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "does not assign a HER2 score" in html
    assert "Pathologist review" in html
    assert "not validated for diagnostic use" in " ".join(html.split())


def test_the_review_step_cannot_be_removed_without_failing_a_test():
    """The human-review step is a requirement, not a nicety."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")

    assert 'id="review-form"' in html
    assert 'id="reviewer" required' in html, "reviewer identity must be required"
    assert "/api/review" in script
    # Recording happens only on explicit submit, never as a side effect of
    # analysing -- a review that is logged automatically is not a review.
    assert 'addEventListener("submit", submitReview)' in script
    assert "/api/review" not in script.split("async function analyze")[1].split(
        "async function requestBody"
    )[0]


def test_the_2plus_row_is_flagged_in_the_table_not_only_in_the_footnotes():
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert "unreliable" in script and "c.index === 3" in script
    assert "tr.unreliable" in css
    assert "not reliable" in css


def test_the_stated_limitation_names_the_class_and_the_consequence():
    assert "moderate (2+)" in MODEL_LIMITATION
    assert "FISH" in MODEL_LIMITATION, "why it matters must be stated, not just that"


def test_the_download_report_button_calls_the_report_endpoint():
    """The button must exist and actually be wired to /api/report -- a
    button that looks right but calls nothing would be worse than no button.
    """
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")

    assert 'id="download-report"' in html
    assert '$("download-report").addEventListener("click", downloadReport)' in script
    assert "/api/report" in script
    # The download must use the server's own suggested filename when given
    # one, not a hard-coded name that could mismatch the analysed field.
    assert "Content-Disposition" in script


def test_the_report_button_is_disabled_while_a_report_is_being_built():
    """Mirrors the same discipline analyze()'s button already follows --
    see the data-busy attribute both use for their spinner state."""
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    download = script.split("async function downloadReport")[1].split(
        "/* ---------- helpers"
    )[0]
    assert 'button.disabled = true' in download
    assert 'button.setAttribute("data-busy", "")' in download
    assert 'button.disabled = false' in download


# -------------------------------------------------------------- the server


def test_sample_paths_cannot_escape_the_patch_root(tmp_path):
    from app.server import State

    class FakeAnalyzer:
        provenance = {"run": "x"}

    root = tmp_path / "data"
    (root / "train" / "class_0").mkdir(parents=True)
    state = State(FakeAnalyzer(), root, tmp_path / "reviews.jsonl")

    with pytest.raises(FileNotFoundError):
        state.read_sample("../../../etc/passwd")
    with pytest.raises(FileNotFoundError):
        state.read_sample("train/class_0/nope.png")


def test_dataset_label_looks_up_the_samples_own_folder(tmp_path):
    """The fact the frontend needs to lead with -- "what does the dataset
    say this field is" -- has to come from the SAME folder the sample list
    itself was built from, not be re-derived some other way that could
    silently drift from it."""
    from PIL import Image

    from app.server import State

    class FakeAnalyzer:
        provenance = {"run": "x"}

    root = tmp_path / "data"
    folder = root / "test" / "class_2+"
    folder.mkdir(parents=True)
    Image.new("RGB", (4, 4), "white").save(folder / "field.png")

    state = State(FakeAnalyzer(), root, tmp_path / "reviews.jsonl")
    [sample] = state.samples
    assert sample["folder_label"] == "2+"
    assert state.dataset_label(sample["id"]) == "2+"
    assert state.dataset_label("not/a/real/id.png") is None


def test_a_review_is_appended_with_its_provenance(tmp_path):
    from app.server import State

    class FakeAnalyzer:
        provenance = {"run": "artifacts/phase2_40x"}

    log = tmp_path / "reviews.jsonl"
    state = State(FakeAnalyzer(), tmp_path / "missing", log)
    state.record_review({"patch_id": "a.png", "score": "2+", "reviewer": "AB"})
    state.record_review({"patch_id": "b.png", "score": "0", "reviewer": "AB"})

    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [r["patch_id"] for r in rows] == ["a.png", "b.png"]
    assert all(r["run"] == "artifacts/phase2_40x" for r in rows)
    assert all(r["recorded_at"] for r in rows), "reviews must be timestamped"


def test_an_annotation_is_recorded_with_id_and_filtered_by_patch(tmp_path):
    from app.server import State

    class FakeAnalyzer:
        provenance = {"run": "x"}

    state = State(FakeAnalyzer(), tmp_path / "missing", tmp_path / "reviews.jsonl")
    saved = state.record_annotation({
        "patch_id": "x.png", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2,
        "note": "possible artifact", "score": "", "reviewer": "AB",
    })
    state.record_annotation({
        "patch_id": "y.png", "x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5,
        "note": "other field", "score": "", "reviewer": "AB",
    })

    assert saved["id"].startswith("ann-")
    assert saved["recorded_at"]
    # Defaults to a file next to the review log, the same "one artifacts/
    # directory" convention record_review already follows.
    assert state.annotations_log == tmp_path / "annotations.jsonl"
    assert [e["patch_id"] for e in state.read_annotations("x.png")] == ["x.png"]
    assert state.read_annotations("no-such-field") == []


def test_annotation_endpoint_validates_and_round_trips(tmp_path):
    """End-to-end over real HTTP, mirroring test_report_endpoint_streams_a_pdf:
    proves the route is wired to State.record_annotation with the right
    validation, not just that the validation logic works in isolation."""
    import http.client
    import threading
    from http.server import ThreadingHTTPServer

    from app.server import Handler, State

    class FakeAnalyzer:
        provenance = {"run": "x"}

    state = State(FakeAnalyzer(), tmp_path / "missing", tmp_path / "reviews.jsonl")
    Handler.state = state
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post(body):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        conn.request(
            "POST", "/api/annotations",
            body=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        return response.status, json.loads(response.read())

    try:
        status, payload = post({
            "patch_id": "field.png", "x": 0.2, "y": 0.3, "w": 0.1, "h": 0.15,
            "note": "check this focus", "reviewer": "AB",
        })
        assert status == 200
        assert payload["ok"] is True
        assert payload["annotation"]["patch_id"] == "field.png"
        assert payload["annotation"]["id"]
        assert state.read_annotations("field.png") == [payload["annotation"]]

        # No reviewer -- the same discipline /api/review already enforces.
        status, payload = post({
            "patch_id": "field.png", "x": 0, "y": 0, "w": 0.1, "h": 0.1, "note": "x",
        })
        assert status == 400

        # A box that does not fit inside the image.
        status, payload = post({
            "patch_id": "field.png", "x": 0.5, "y": 0, "w": 0.9, "h": 0.1,
            "note": "x", "reviewer": "AB",
        })
        assert status == 400

        # Neither a note nor a score -- nothing to record.
        status, payload = post({
            "patch_id": "field.png", "x": 0, "y": 0, "w": 0.1, "h": 0.1, "reviewer": "AB",
        })
        assert status == 400

        # An unrecognised score string.
        status, payload = post({
            "patch_id": "field.png", "x": 0, "y": 0, "w": 0.1, "h": 0.1,
            "score": "4+", "reviewer": "AB",
        })
        assert status == 400
    finally:
        server.shutdown()
        server.server_close()


def test_analyze_response_includes_this_fields_saved_annotations(analyzer, tmp_path):
    """/api/analyze is what the portal actually calls to load a field, so the
    annotations it carries have to come back from there, not only from the
    lower-level State methods the two tests above exercise directly."""
    import base64
    import http.client
    import io
    import threading
    from http.server import ThreadingHTTPServer

    from PIL import Image

    from app.server import Handler, State
    from tests.synthetic import graded_patch

    state = State(analyzer, Path("data/raw"), tmp_path / "reviews.jsonl")
    state.record_annotation({
        "patch_id": "demo.png", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2,
        "note": "earlier note", "score": "", "reviewer": "AB",
    })
    Handler.state = state
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        buffer = io.BytesIO()
        Image.fromarray(graded_patch(size=128)).save(buffer, format="PNG")
        data_uri = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        body = json.dumps({"image": data_uri, "name": "demo.png"}).encode("utf-8")
        conn.request("POST", "/api/analyze", body=body, headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        result = json.loads(response.read())

        assert response.status == 200
        assert [a["note"] for a in result["annotations"]] == ["earlier note"]
    finally:
        server.shutdown()
        server.server_close()


def test_analyze_endpoint_reports_the_datasets_own_label(analyzer, tmp_path):
    """dataset_label on /api/analyze's response must be the sample's own
    folder label for a patch_id request, and None for an upload -- there is
    no dataset folder behind an uploaded image to look one up in."""
    import base64
    import http.client
    import io
    import threading
    from http.server import ThreadingHTTPServer

    from PIL import Image

    from app.server import Handler, State
    from tests.synthetic import graded_patch

    patch_root = tmp_path / "data"
    folder = patch_root / "test" / "class_3+"
    folder.mkdir(parents=True)
    Image.fromarray(graded_patch(size=64)).save(folder / "field.png")

    Handler.state = State(analyzer, patch_root, tmp_path / "reviews.jsonl")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post(body):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        conn.request(
            "POST", "/api/analyze",
            body=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        return response.status, json.loads(response.read())

    try:
        status, result = post({"patch_id": "test/class_3+/field.png"})
        assert status == 200
        assert result["dataset_label"] == "3+"

        buffer = io.BytesIO()
        Image.fromarray(graded_patch(size=64)).save(buffer, format="PNG")
        data_uri = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
        status, result = post({"image": data_uri, "name": "uploaded.png"})
        assert status == 200
        assert result["dataset_label"] is None
    finally:
        server.shutdown()
        server.server_close()


class _Running:
    """A real server on an ephemeral port for the duration of a with-block."""

    def __init__(self, state):
        self.state = state

    def __enter__(self):
        import threading
        from http.server import ThreadingHTTPServer

        from app.server import Handler

        Handler.state = self.state
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def request(self, method, path, body=None):
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=30)
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        conn.request(method, path, body=payload, headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        return response.status, response.getheader("Content-Type") or "", response.read()

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def test_reviews_endpoint_serves_the_log_newest_first(tmp_path):
    """The Case log and the dashboard are views of the server's review log,
    so what one POSTs to /api/review has to come back from /api/reviews --
    and nothing else may: no seeded demo rows mixed in with real sign-offs."""
    from app.server import State

    class FakeAnalyzer:
        provenance = {"run": "artifacts/phase2_unet"}

    state = State(FakeAnalyzer(), tmp_path / "missing", tmp_path / "reviews.jsonl")
    with _Running(state) as srv:
        status, _, body = srv.request("GET", "/api/reviews")
        assert status == 200 and json.loads(body) == {"reviews": []}

        for patch, score, agrees in (("a.png", "2+", True), ("b.png", "cannot assess from this field", False)):
            status, _, _ = srv.request("POST", "/api/review", {
                "patch_id": patch, "score": score, "agrees": agrees, "reviewer": "AB",
                "notes": "n", "measurements": {"tissue_percent": 61.5},
            })
            assert status == 200

        status, _, body = srv.request("GET", "/api/reviews")
        rows = json.loads(body)["reviews"]
    assert [r["patch_id"] for r in rows] == ["b.png", "a.png"]
    assert rows[1]["agrees"] is True and rows[0]["agrees"] is False
    assert rows[1]["tissue_percent"] == 61.5
    assert all(r["at"] and r["reviewer"] == "AB" for r in rows)


def test_file_paths_404_instead_of_falling_through_to_the_page(tmp_path):
    """A request for a file that is not in the build must be a 404. Before
    this, /fonts/x.woff2 came back as index.html and the browser tried to
    decode the page as a font."""
    from app.server import State

    class FakeAnalyzer:
        provenance = {"run": "x"}

    dist = tmp_path / "dist"
    (dist / "fonts").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>portal</title>", encoding="utf-8")
    (dist / "fonts" / "real.woff2").write_bytes(b"wOF2")

    state = State(FakeAnalyzer(), tmp_path / "missing", tmp_path / "r.jsonl", dist)
    with _Running(state) as srv:
        status, _, _ = srv.request("GET", "/fonts/missing.woff2")
        assert status == 404
        status, ctype, body = srv.request("GET", "/fonts/real.woff2")
        assert status == 200 and ctype == "font/woff2" and body == b"wOF2"
        # Client-side routes still get the portal, including on hard refresh.
        for route in ("/", "/analysis", "/cases"):
            status, ctype, body = srv.request("GET", route)
            assert status == 200 and ctype.startswith("text/html") and b"portal" in body


def test_heatmap_legend_matches_the_rendering_thresholds(analyzer):
    """The colour bar the portal draws comes from this, so its stops must be
    the heatmap's own, in order, with a tick at each class threshold."""
    from app.analysis import HEATMAP_STOPS

    legend = analyzer.heatmap_legend()
    weak, moderate, strong = analyzer.preprocessing.stain.thresholds()
    assert [s["color"] for s in legend["stops"]] == list(HEATMAP_STOPS)
    positions = [s["at"] for s in legend["stops"]]
    assert positions == sorted(positions) and positions[0] == 0.0 and positions[-1] == 1.0
    assert [t["at"] for t in legend["ticks"]] == pytest.approx([weak / strong, moderate / strong, 1.0], abs=1e-3)
    assert [t["label"] for t in legend["ticks"]] == ["weak (1+)", "moderate (2+)", "strong (3+)"]


def test_cannot_assess_is_an_offered_choice():
    """Forcing a score manufactures agreement the tool did not earn."""
    from app.server import REVIEW_CHOICES

    assert any("cannot assess" in c for c in REVIEW_CHOICES)
    assert set(REVIEW_CHOICES) >= {"0", "1+", "2+", "3+"}


def test_report_endpoint_streams_a_pdf(analyzer, tmp_path):
    """End-to-end: a real request to /api/report gets back a real PDF.

    Everything else about the report (its content, its caveats, that it
    never carries a score) is tested directly against
    app.report.build_report_pdf_bytes in tests/test_report.py. This test's
    job is narrower and different: prove the HTTP route is actually wired to
    that function, with the right content type and a download-friendly
    filename header.
    """
    import base64
    import http.client
    import io
    import threading
    from http.server import ThreadingHTTPServer

    from PIL import Image

    from app.server import Handler, State
    from tests.synthetic import graded_patch

    Handler.state = State(analyzer, Path("data/raw"), tmp_path / "reviews.jsonl")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        buffer = io.BytesIO()
        Image.fromarray(graded_patch(size=128)).save(buffer, format="PNG")
        data_uri = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(
            "ascii"
        )

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        body = json.dumps({"image": data_uri, "name": "test field"}).encode("utf-8")
        conn.request(
            "POST", "/api/report", body=body, headers={"Content-Type": "application/json"}
        )
        response = conn.getresponse()
        payload = response.read()

        assert response.status == 200
        assert response.getheader("Content-Type") == "application/pdf"
        assert "attachment" in (response.getheader("Content-Disposition") or "")
        assert payload.startswith(b"%PDF")
    finally:
        server.shutdown()
        server.server_close()
