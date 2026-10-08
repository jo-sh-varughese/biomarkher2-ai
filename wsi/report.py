"""Whole-slide HER2 pre-scoring report (PDF).

Same structure and safety wording as the field report (app/report.py), at
slide level:

1. Summary -- slide pre-score (or why it is withheld), suggested next steps
   including ISH, ASCO/CAP evidence over every invasive tumour cell measured,
   pathologist confirmation block.
2. Where -- slide overview with the invasive-tumour map and the per-field
   grade map, and the hotspot fields that weighed most, each with its cell
   membrane map.
3. Fields, method and limitations.
"""

from __future__ import annotations

import base64
import io
from datetime import datetime

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Image as RLImage
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.report import CONTENT_WIDTH, MUTED, PAGE_MARGIN, REPORT_FOOTER, _escape, _grid, _styles, _summary_page


def _img(data_uri: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data_uri.split(",", 1)[-1])))


def _rl(image: Image.Image, width) -> RLImage:
    image = image.convert("RGB")
    if image.width > 1400:
        image = image.resize((1400, int(image.height * 1400 / image.width)))
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=88)
    buf.seek(0)
    return RLImage(buf, width=width, height=width * image.height / image.width)


def _composite(result: dict, which: str) -> Image.Image:
    base = _img(result["images"]["overview"]).convert("RGBA")
    over = _img(result["images"][which]).convert("RGBA").resize(base.size, Image.NEAREST)
    return Image.alpha_composite(base, over)


def _meta(result: dict) -> str:
    info, tis = result["slide"], result.get("tissue", {})
    mpp = f"{info['mpp']:.3f} um/px" if info.get("mpp") else "um/px unknown"
    return (f"Slide <b>{_escape(info['path'].replace(chr(92), '/').split('/')[-1])}</b> &middot; {info['width']}&times;{info['height']} px "
            f"&middot; {mpp} &middot; scanner {_escape(info.get('vendor', '-'))} &middot; fields analysed "
            f"{len(result.get('fields', []))} &middot; usable tissue {tis.get('usable_area_mm2', 0)} mm&sup2; &middot; "
            f"generated {datetime.now():%Y-%m-%d %H:%M}")


def build_slide_report_pdf_bytes(result: dict) -> bytes:
    st = _styles()
    buffer = io.BytesIO()
    title = result["slide"]["path"].replace("\\", "/").split("/")[-1]
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN,
                            topMargin=PAGE_MARGIN, bottomMargin=PAGE_MARGIN, title=f"BioMarkHER2 -- {title}")

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(PAGE_MARGIN, 8 * mm, f"BioMarkHER2 whole-slide report -- {title[:60]}")
        canvas.drawRightString(A4[0] - PAGE_MARGIN, 8 * mm, f"page {doc_.page} -- AI suggestions require pathologist confirmation")
        canvas.restoreState()

    from app.report import _decision_page

    flow = _summary_page(result, st, title="HER2 IHC whole-slide pre-scoring report", meta=_meta(result))
    if result.get("flags"):
        flow.append(Spacer(1, 2 * mm))
        flow.append(Paragraph("<b>Slide-level flags</b>" + "".join(f"<br/>&#9888; {_escape(f)}" for f in result["flags"]), st["small"]))
    flow.append(PageBreak())
    decision_pages = _decision_page(result, st)
    if decision_pages:
        flow += decision_pages + [PageBreak()]

    # ---- where
    flow.append(Paragraph("Where the fields are and what was excluded", st["title"]))
    half = CONTENT_WIDTH / 2 - 3 * mm
    maps = Table([[Paragraph("<b>Excluded tissue</b>", st["body"]), Paragraph("<b>Per-field grade map</b>", st["body"])],
                  [_rl(_composite(result, "excluded_overlay"), half), _rl(_composite(result, "grade_overlay"), half)],
                  [Paragraph("Teal: on-slide control tissue; grey: blue ink or mounting film. Both are left out of the patient's evidence.", st["small"]),
                   Paragraph("Each analysed field coloured by its grade: grey 0, yellow 1+, orange 2+, red 3+.", st["small"])]],
                 colWidths=[CONTENT_WIDTH / 2] * 2)
    maps.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    flow.append(maps)
    hot = result.get("hotspots") or []
    if hot:
        flow.append(Paragraph("Hotspot fields (weighed most in the slide pre-score)", st["h"]))
        cells = []
        w3 = CONTENT_WIDTH / 3 - 3 * mm
        for h in hot:
            cap = (f"Field {h['index'] + 1}: AI {h.get('prescore_category') or '-'} &middot; cells {h['cell_category']} "
                   f"&middot; {h['cells']} cells" + (f" &middot; weight {h['attention']:.0%}" if h.get("attention") is not None else ""))
            cells.append([_rl(_img(h["image"]), w3), _rl(_img(h["cells_image"]), w3), Paragraph(cap, st["small"])])
        rows = []
        for h in cells:
            rows.append([h[0], h[1], h[2]])
        t = Table(rows, colWidths=[w3 + 2 * mm, w3 + 2 * mm, w3 + 2 * mm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        flow.append(t)
    flow.append(PageBreak())

    # ---- fields + method
    flow.append(Paragraph("Fields, method and limitations", st["title"]))
    fields = result.get("fields") or []
    if fields:
        data = [["Field", "Position (x, y)", "Tissue", "Cells", "AI grade", "Cell grade", "Weight"]]
        for f in fields:
            data.append([str(f["index"] + 1), f"{f['x']}, {f['y']}", f"{f['tissue_fraction']:.0%}", str(f["cells"]),
                         f.get("prescore_category") or "-", f["cell_category"],
                         f"{f['attention']:.0%}" if f.get("attention") is not None else "-"])
        flow.append(_grid(data, [14 * mm, 38 * mm, 20 * mm, 18 * mm, 20 * mm, 22 * mm, 20 * mm]))
    ctl = result.get("stain_control") or {}
    lines = [
        "<b>Fields</b>: 40x fields (about 246 um) spread over the usable tissue. Tumour is <b>not segmented</b>: "
        "stroma, in-situ carcinoma and normal ducts can fall inside a field, and ASCO/CAP scores invasive tumour only, "
        "so the pathologist confirms that each field lies in invasive tumour.",
        "<b>Exclusions</b>: on-slide control cores and blue ink or mounting film are detected and left out of the evidence; "
        "they are drawn on the map above.",
        "<b>Slide pre-score</b>: the field model's attention pooling over every tile analysed.",
    ]
    if ctl.get("cores_found"):
        lines.append("<b>On-slide control</b>: " + _escape(ctl.get("reason") or "measured") +
                     (f" Strongest core DAB p90 {ctl['strongest_p90']}." if ctl.get("strongest_p90") is not None else ""))
    for line in lines:
        flow.append(Paragraph(line, st["body"]))
        flow.append(Spacer(1, 1.5 * mm))
    flow.append(Paragraph("Limitations", st["h"]))
    for text in list((result.get("caveats") or {}).values()) + list(result.get("flags") or []):
        flow.append(Paragraph(f"&bull; {_escape(text)}", st["small"]))
    flow.append(Spacer(1, 4 * mm))
    flow.append(Paragraph(REPORT_FOOTER, st["small"]))
    doc.build(flow, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
