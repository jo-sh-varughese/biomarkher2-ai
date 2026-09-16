"""Tests for scripts/batch_report.py -- the batch/summary report tool.

Mirrors tests/test_app.py's pattern: build a real (untrained, so no download
or long training run is needed) Analyzer and scan its real output, rather
than only checking the script's source text for forbidden literal strings.
A source-text scan can never catch a bug in *which* field actually lands in
the CSV -- which is exactly what shipped here the first time: the
disagreement column was read from a key ("agreement") that
PatchAnalysis.to_dict() never produces, so it was silently blank on every
row. test_batch_report_disagreement_column_is_populated is the regression
test for that; see PHASE6_NOTES.md for the full story.
"""

from __future__ import annotations

import csv
import json

import numpy as np
import pytest
import torch
from PIL import Image

from app.analysis import Analyzer
from models import select_architecture
from scripts.batch_report import FORBIDDEN_FIELDS, run_batch_report, write_report
from tests.synthetic import graded_patch
from training.config import TrainingConfig


@pytest.fixture(scope="module")
def analyzer(tmp_path_factory):
    """A real Analyzer over an untrained model, so no download is needed."""
    root = tmp_path_factory.mktemp("batch_report_app")
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


@pytest.fixture
def patch_dir(tmp_path):
    directory = tmp_path / "patches"
    directory.mkdir()
    for index in range(2):
        image = graded_patch(size=64)
        Image.fromarray(image).save(directory / f"patch_{index}.png")
    return directory


def test_batch_report_rows_have_no_forbidden_fields(analyzer, patch_dir):
    image_paths = sorted(patch_dir.iterdir())
    rows = run_batch_report(analyzer, image_paths)

    assert rows
    fieldnames = list(rows[0].keys())
    forbidden = {name.lower() for name in fieldnames if name.lower() in FORBIDDEN_FIELDS}
    assert not forbidden

    # Also scan the actual values, not just field names -- a forbidden word
    # smuggled into a value would slip past a fieldnames-only check.
    flat = json.dumps(rows).lower()
    for word in ('"score"', '"her2_score"', '"verdict"', '"diagnosis"'):
        assert word not in flat


def test_batch_report_disagreement_column_is_populated(analyzer, patch_dir):
    """Regression test for the blank-`agreement`-column bug (see module
    docstring): every row's disagreement figure must be a real number, not
    None, and must be a valid percentage."""
    image_paths = sorted(patch_dir.iterdir())
    rows = run_batch_report(analyzer, image_paths)

    assert rows
    for row in rows:
        assert row["disagreement_percent"] is not None
        assert 0.0 <= row["disagreement_percent"] <= 100.0


def test_batch_report_one_row_per_patch_with_tissue_and_class_columns(analyzer, patch_dir):
    image_paths = sorted(patch_dir.iterdir())
    rows = run_batch_report(analyzer, image_paths)

    assert len(rows) == len(image_paths)
    for row, path in zip(rows, image_paths):
        assert row["patch_id"] == path.name
        assert 0.0 <= row["tissue_percent"] <= 100.0
        assert any(key.startswith("model_") for key in row)
        assert any(key.startswith("baseline_") for key in row)


def test_batch_report_writes_a_valid_csv_with_no_forbidden_fields(analyzer, patch_dir, tmp_path):
    image_paths = sorted(patch_dir.iterdir())
    rows = run_batch_report(analyzer, image_paths)
    output_path = tmp_path / "report.csv"
    write_report(rows, output_path)

    assert output_path.is_file()
    with output_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        written_rows = list(reader)
        fieldnames = reader.fieldnames or []

    assert len(written_rows) == len(image_paths)
    assert not {name.lower() for name in fieldnames} & FORBIDDEN_FIELDS
    for row in written_rows:
        # Round-tripped through CSV as text, but must not be empty/blank.
        assert row["disagreement_percent"] not in (None, "")


def test_write_report_rejects_a_forbidden_field_name():
    with pytest.raises(RuntimeError, match="Forbidden output fields"):
        write_report([{"patch_id": "x", "score": 3}], None)  # type: ignore[arg-type]


def test_write_report_rejects_empty_rows(tmp_path):
    with pytest.raises(SystemExit):
        write_report([], tmp_path / "report.csv")
