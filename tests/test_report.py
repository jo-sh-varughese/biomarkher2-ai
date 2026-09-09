"""Tests for the offline PDF report generator.

The one property that matters most here mirrors tests/test_app.py's rule for
the live API: the report must never carry a HER2 score, verdict or
diagnosis. It is built from exactly the same dict the live API returns, so
this is largely a consequence of that guarantee rather than a new one -- but
it is asserted directly here too, since a future change to report.py could
add a field the API dict does not have.
"""

from __future__ import annotations

import base64
import io

import numpy as np
from PIL import Image
from pypdf import PdfReader

from app.report import build_report_pdf, build_report_pdf_bytes


def _tiny_png_data_uri(color: tuple[int, int, int] = (200, 120, 40)) -> str:
    image = Image.fromarray(np.full((8, 8, 3), color, dtype=np.uint8))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def sample_analysis() -> dict:
    return {
        "patch_id": "uploaded field 001",
        "width": 512,
        "height": 512,
        "tissue_percent": 71.2,
        "model_percentages": {
            "negative": 40.0, "weak (1+)": 30.0, "moderate (2+)": 20.0, "strong (3+)": 10.0,
        },
        "baseline_percentages": {
            "negative": 42.0, "weak (1+)": 28.0, "moderate (2+)": 19.0, "strong (3+)": 11.0,
        },
        "disagreement_percent": 6.4,
        "images": {
            "original": _tiny_png_data_uri((220, 220, 220)),
            "tissue": _tiny_png_data_uri((240, 240, 240)),
            "model": _tiny_png_data_uri((200, 120, 40)),
            "baseline": _tiny_png_data_uri((150, 90, 30)),
        },
        "caveats": {
            "not_a_score": "This is a pre-scoring measurement aid. It does not "
            "assign a HER2 score and is not a diagnosis.",
            "model_limitation": "This model does not reliably predict the "
            "moderate (2+) class.",
        },
    }


def _extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_build_report_pdf_writes_a_readable_pdf(tmp_path):
    path = build_report_pdf(sample_analysis(), tmp_path / "report.pdf")
    assert path.is_file()
    assert path.read_bytes().startswith(b"%PDF")


def test_report_bytes_and_file_output_carry_the_same_content(tmp_path):
    analysis = sample_analysis()
    from_bytes = _extract_text(build_report_pdf_bytes(analysis))
    path = build_report_pdf(analysis, tmp_path / "report.pdf")
    from_file = _extract_text(path.read_bytes())
    assert from_bytes == from_file


def test_report_never_contains_a_score_verdict_or_diagnosis_field():
    text = _extract_text(build_report_pdf_bytes(sample_analysis())).lower()
    for forbidden in ("her2 score:", "verdict:", "diagnosis:"):
        assert forbidden not in text
    assert "does not assign a her2 score" in text


def test_report_includes_the_patch_id_and_measurements():
    text = _extract_text(build_report_pdf_bytes(sample_analysis()))
    assert "uploaded field 001" in text
    assert "40.00%" in text  # model negative percentage
    assert "42.00%" in text  # baseline negative percentage


def test_report_carries_every_caveat():
    analysis = sample_analysis()
    text = _extract_text(build_report_pdf_bytes(analysis))
    for caveat_text in analysis["caveats"].values():
        # PDF text extraction can wrap lines; check the first clause survives.
        assert caveat_text.split(".")[0] in text


def test_report_handles_missing_images_gracefully():
    analysis = sample_analysis()
    analysis["images"] = {}
    pdf_bytes = build_report_pdf_bytes(analysis)
    assert pdf_bytes.startswith(b"%PDF")
