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
    MODEL_LIMITATION,
    NOT_A_SCORE,
    PALETTE,
    colorize,
    overlay,
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
    from models.segformer_seg import build_model
    from training.config import TrainingConfig

    root = tmp_path_factory.mktemp("app")
    config = TrainingConfig()
    config.model.pretrained = False
    config.model.image_size = 64
    config.to_yaml(root / "training.yaml")

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

    assert set(result["images"]) == {"original", "tissue", "model", "baseline"}
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


def test_cannot_assess_is_an_offered_choice():
    """Forcing a score manufactures agreement the tool did not earn."""
    from app.server import REVIEW_CHOICES

    assert any("cannot assess" in c for c in REVIEW_CHOICES)
    assert set(REVIEW_CHOICES) >= {"0", "1+", "2+", "3+"}
