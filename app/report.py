"""PDF export of one analysis -- Objective 4's "report generation".

    from app.report import build_report_pdf
    build_report_pdf(analysis, Path("report.pdf"))

This exports exactly what the viewer already shows and nothing it does not.
That constraint is deliberate, not an oversight: the report is built directly
from :meth:`app.analysis.PatchAnalysis.to_dict`, the same payload
``tests/test_app.py`` scans to guarantee no ``score``/``verdict``/``diagnosis``
field exists anywhere in the live API. A report generator that quietly added
a CAP category or a status label the live JSON does not carry would
reintroduce exactly what that test exists to prevent, just in a different
file format. If a reader wants the offline CAP/ASCO mapping analysis, that
lives in evaluation/cap_mapping.py and is a separate, clearly-labelled
research artifact -- see its module docstring for why it stays separate.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

PAGE_MARGIN = 16 * mm
IMAGE_PANEL_WIDTH = 82 * mm

REPORT_FOOTER = (
    "BioMarkHER2 -- final-year project, developed with Government Medical "
    "College Kottayam. Research and workflow-support use only. Not a "
    "medical device and not validated for diagnostic use. This report "
    "does not assign a HER2 score; a qualified pathologist does."
)

PANEL_TITLES = {
    "original": "Original field",
    "tissue": "Detected tissue",
    "model": "Model intensity map",
    "baseline": "Threshold baseline",
    "ambiguity": "Prediction confidence",
}


def _data_uri_to_image(data_uri: str, max_width_px: int = 640) -> RLImage:
    """Decode one of PatchAnalysis's base64 PNG data URIs into a flowable."""
    _, encoded = data_uri.split(",", 1)
    raw = base64.b64decode(encoded)
    with Image.open(io.BytesIO(raw)) as img:
        width, height = img.size
    aspect = height / width if width else 1.0
    return RLImage(io.BytesIO(raw), width=IMAGE_PANEL_WIDTH, height=IMAGE_PANEL_WIDTH * aspect)


def build_report_pdf(analysis_dict: dict, path: str | Path) -> Path:
    """Render one :meth:`PatchAnalysis.to_dict` payload to a PDF at ``path``.

    Takes the plain dict rather than a ``PatchAnalysis`` object so it can be
    called from the server (which already has the dict, freshly built for
    the JSON response) without importing torch/the model into a code path
    that only ever touches already-computed numbers and images.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _render(analysis_dict, str(path), title_for=path.name)
    return path


def build_report_pdf_bytes(analysis_dict: dict) -> bytes:
    """Same report, returned as PDF bytes rather than written to disk.

    Used by app/server.py so a download can be streamed straight from an
    in-memory analysis without a temporary file on disk holding a patient
    field between request and response.
    """
    buffer = io.BytesIO()
    _render(analysis_dict, buffer, title_for=analysis_dict.get("patch_id", "analysis"))
    return buffer.getvalue()


def _render(analysis_dict: dict, target, title_for: str) -> None:
    styles = getSampleStyleSheet()
    caveat_style = ParagraphStyle(
        "Caveat", parent=styles["BodyText"], fontSize=8.5, leading=11, textColor=colors.HexColor("#4a4238")
    )
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"], fontSize=17, spaceAfter=2,
    )

    doc = SimpleDocTemplate(
        target,
        pagesize=A4,
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN,
        title=f"BioMarkHER2 -- {title_for}",
    )

    flow = []
    flow.append(Paragraph("BioMarkHER2 -- pre-scoring measurement report", title_style))
    flow.append(
        Paragraph(
            f"Field: <b>{_escape(analysis_dict.get('patch_id', ''))}</b> "
            f"&nbsp;&nbsp; {analysis_dict.get('width')}&times;{analysis_dict.get('height')} px "
            f"&nbsp;&nbsp; tissue detected: {analysis_dict.get('tissue_percent')}% of frame",
            styles["BodyText"],
        )
    )
    flow.append(Spacer(1, 4 * mm))
    flow.append(
        Paragraph(
            "<b>This report does not assign a HER2 score.</b> It measures "
            "stained tissue area and shows where the staining is, so that a "
            "pathologist can score the case faster and more consistently. "
            "Every result below requires review and confirmation by a "
            "qualified pathologist.",
            caveat_style,
        )
    )
    flow.append(Spacer(1, 5 * mm))

    images = analysis_dict.get("images") or {}
    if images:
        cells = []
        for key in ("original", "tissue", "model", "baseline", "ambiguity"):
            if key not in images:
                continue
            cell = [
                Paragraph(f"<b>{PANEL_TITLES.get(key, key)}</b>", styles["BodyText"]),
                _data_uri_to_image(images[key]),
            ]
            cells.append(cell)
        if cells:
            rows = [cells[i : i + 2] for i in range(0, len(cells), 2)]
            image_table = Table(rows, hAlign="LEFT")
            image_table.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ]
                )
            )
            flow.append(image_table)
            flow.append(Spacer(1, 4 * mm))

    flow.append(Paragraph("Stained area, as a percentage of detected tissue", styles["Heading3"]))
    flow.append(
        Paragraph("Not a percentage of tumour cells -- see the notes below.", caveat_style)
    )
    model_pct = analysis_dict.get("model_percentages") or {}
    baseline_pct = analysis_dict.get("baseline_percentages") or {}
    class_names = sorted(set(model_pct) | set(baseline_pct))
    table_data = [["Intensity class", "Model", "Threshold baseline", "Difference"]]
    for name in class_names:
        m = model_pct.get(name, 0.0)
        b = baseline_pct.get(name, 0.0)
        table_data.append([name, f"{m:.2f}%", f"{b:.2f}%", f"{m - b:+.2f} pp"])
    area_table = Table(table_data, hAlign="LEFT", colWidths=[55 * mm, 30 * mm, 42 * mm, 30 * mm])
    area_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eee6d8")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9bfa8")),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ]
        )
    )
    flow.append(area_table)
    flow.append(Spacer(1, 3 * mm))
    disagreement = analysis_dict.get("disagreement_percent")
    if disagreement is not None:
        flow.append(
            Paragraph(
                f"Model and baseline disagree on {disagreement}% of tissue pixels.",
                styles["BodyText"],
            )
        )
    flow.append(Spacer(1, 6 * mm))

    flow.append(Paragraph("What these numbers are, and are not", styles["Heading3"]))
    caveats = analysis_dict.get("caveats") or {}
    for text in caveats.values():
        flow.append(Paragraph(f"&bull; {_escape(text)}", caveat_style))
        flow.append(Spacer(1, 1.5 * mm))

    flow.append(Spacer(1, 6 * mm))
    flow.append(Paragraph(REPORT_FOOTER, caveat_style))

    doc.build(flow)


def _escape(text: object) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
