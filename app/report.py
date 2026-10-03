"""HER2 IHC pre-scoring report (PDF) for the pathologist.

    from app.report import build_report_pdf
    build_report_pdf(analysis, Path("report.pdf"))

Built from :meth:`app.analysis.PatchAnalysis.to_dict` -- exactly what the
viewer shows, nothing more. Three pages:

1. **Summary** -- the AI pre-score (or why it is withheld at this site), the
   suggested next steps including whether ISH is indicated, the cell-level
   ASCO/CAP evidence, and a confirmation block the pathologist completes.
2. **Visual explanation** -- cell membrane map, AI evidence heatmap, regional
   pre-scores with attention, intensity maps, and the per-region table.
3. **Measurements, method and limitations.**

Every pre-score in this report is a suggestion requiring pathologist
confirmation; the report never states a verdict or a diagnosis.
"""

from __future__ import annotations

import base64
import io
from datetime import datetime
from pathlib import Path

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image as RLImage
from reportlab.platypus import CondPageBreak, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

PAGE_MARGIN = 15 * mm
CONTENT_WIDTH = A4[0] - 2 * PAGE_MARGIN
IMAGE_PANEL_WIDTH = 86 * mm

INK = colors.HexColor("#1f2329")
MUTED = colors.HexColor("#5b6270")
RULE = colors.HexColor("#d5d9e0")
PANEL = colors.HexColor("#f4f6f9")
GRADE_COLORS = {"0": "#6e82a0", "1+": "#d9b230", "2+": "#e08214", "3+": "#c81e28"}
ISH_STYLE = {
    "required": ("ISH REQUIRED", "#b3261e", "#fbe9e7"),
    "recommended": ("ISH / SECOND REVIEW RECOMMENDED", "#9a5b00", "#fff4e0"),
    "not_indicated_by_ihc": ("ISH NOT INDICATED BY IHC", "#1e6b45", "#e6f4ec"),
    "not_applicable": ("NOT ASSESSABLE", "#5b6270", "#eef0f3"),
}

REPORT_FOOTER = (
    "BioMarkHER2 -- final-year project, developed with Government Medical College Kottayam. Research and "
    "workflow-support use. Not a certified medical device. Any AI pre-score is a suggestion that a qualified "
    "pathologist must confirm; the pathologist assigns the HER2 score and decides on ISH testing."
)

PANEL_TITLES = {
    "original": ("Original field", "As scanned."),
    "cells": ("Cell membrane map", "Each detected cell's membrane, coloured by its ASCO/CAP category: "
              "grey 0, yellow 1+, orange 2+, red 3+."),
    "evidence": ("AI evidence heatmap", "Where the model found evidence for its pre-score (Grad-CAM): "
                 "red = strongest evidence."),
    "regions": ("Regional pre-scores", "Each region tinted by its own pre-score; thicker border = more weight "
                "in the overall pre-score."),
    "model": ("Model intensity map", "Pixel intensity classes from the segmentation model."),
    "heatmap": ("DAB intensity heatmap", "Raw DAB darkness; ticks at the weak / moderate / strong cut points."),
    "baseline": ("Threshold baseline", "The classical DAB-threshold rule, shown beside the model as a control."),
    "ambiguity": ("Prediction confidence", "Purple = the model is uncertain at that pixel."),
}


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=17, leading=20, textColor=INK, alignment=0, spaceAfter=1),
        "h": ParagraphStyle("h", parent=base["Heading3"], fontSize=11.5, leading=14, textColor=INK, spaceBefore=6, spaceAfter=3),
        "body": ParagraphStyle("b", parent=base["BodyText"], fontSize=9, leading=12, textColor=INK),
        "small": ParagraphStyle("s", parent=base["BodyText"], fontSize=7.8, leading=10, textColor=MUTED),
        "big": ParagraphStyle("g", parent=base["BodyText"], fontSize=26, leading=30, textColor=INK),
        "label": ParagraphStyle("l", parent=base["BodyText"], fontSize=7.5, leading=9, textColor=MUTED),
    }


def _data_uri_to_image(data_uri: str, max_width_px: int = 640, width=IMAGE_PANEL_WIDTH) -> RLImage:
    raw = base64.b64decode(data_uri.split(",", 1)[-1])
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    if image.width > max_width_px:
        image = image.resize((max_width_px, int(image.height * max_width_px / image.width)))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88)  # PNG made each report ~6 MB; JPEG q88 is visually identical
    buffer.seek(0)
    return RLImage(buffer, width=width, height=width * image.height / image.width)


def build_report_pdf(analysis_dict: dict, path: str | Path) -> Path:
    path = Path(path)
    _render(analysis_dict, str(path), str(analysis_dict.get("patch_id", "")))
    return path


def build_report_pdf_bytes(analysis_dict: dict) -> bytes:
    buffer = io.BytesIO()
    _render(analysis_dict, buffer, str(analysis_dict.get("patch_id", "")))
    return buffer.getvalue()


def _escape(text: object) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _boxed(rows, background=PANEL, border=RULE, widths=None):
    t = Table(rows, colWidths=widths or [CONTENT_WIDTH])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), background), ("BOX", (0, 0), (-1, -1), 0.6, border),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def _grid(data, widths, header=True, align_right_from=1):
    t = Table(data, colWidths=widths, hAlign="LEFT")
    style = [("FONTSIZE", (0, 0), (-1, -1), 8.5), ("GRID", (0, 0), (-1, -1), 0.4, RULE),
             ("ALIGN", (align_right_from, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9edf2")), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    t.setStyle(TableStyle(style))
    return t


def _prob_bars(probs: dict, st) -> Table:
    rows = []
    for grade in ("0", "1+", "2+", "3+"):
        p = float(probs.get(grade, 0.0))
        bar = Table([[""]], colWidths=[max(0.5, 60 * mm * p)], rowHeights=[3.2 * mm])
        bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(GRADE_COLORS[grade]))]))
        rows.append([Paragraph(f"<b>{grade}</b>", st["body"]), bar, Paragraph(f"{p:.0%}", st["body"])])
    t = Table(rows, colWidths=[9 * mm, 62 * mm, 14 * mm], hAlign="LEFT")
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    return t


def _summary_page(a: dict, st, title: str = "HER2 IHC pre-scoring report", meta: str | None = None) -> list:
    flow = []
    pre = a.get("ai_prescore") or {}
    guide = a.get("guidance") or {}
    cells = a.get("cell_evidence") or {}
    flow.append(Paragraph(title, st["title"]))
    model = (pre.get("prescore") or {}).get("model") or {}
    meta = meta or (f"Field <b>{_escape(a.get('patch_id', ''))}</b> &middot; {a.get('width')}&times;{a.get('height')} px &middot; "
            f"tissue {a.get('tissue_percent')}% of frame &middot; site <b>{_escape(pre.get('site') or '-')}</b> &middot; "
            f"generated {datetime.now():%Y-%m-%d %H:%M}")
    flow.append(Paragraph(meta, st["small"]))
    flow.append(Spacer(1, 4 * mm))

    # --- AI pre-score -------------------------------------------------------
    if pre.get("shown") and pre.get("prescore"):
        p = pre["prescore"]
        grade_colour = GRADE_COLORS.get(p["category"], "#1f2329")
        left = [Paragraph("AI PRE-SCORE (suggestion)", st["label"]),
                Paragraph(f'<font color="{grade_colour}"><b>IHC {p["category"]}</b></font>', st["big"]),
                Paragraph(f"Confidence {p['confidence']:.0%} &middot; runner-up {p['runner_up']} "
                          f"(margin {p['margin_to_runner_up']:.0%})" + (" &middot; <b>borderline</b>" if p.get("borderline") else ""),
                          st["small"])]
        ps = p.get("prediction_set") or {}
        if ps.get("available"):
            left.append(Paragraph(f"<b>{round(ps['coverage'] * 100)}% prediction set: IHC {' or '.join(ps['grades']) or 'none'}</b> "
                                  f"(conformal, calibrated on {ps['n_cases']} cases at this site)", st["small"]))
        if p.get("heterogeneity", {}).get("heterogeneous"):
            left.append(Paragraph("<b>Regional heterogeneity detected</b> -- see page 2.", st["small"]))
        right = [Paragraph("Probability by grade", st["label"]), _prob_bars(p["probabilities"], st)]
        box = Table([[left, right]], colWidths=[CONTENT_WIDTH * 0.45, CONTENT_WIDTH * 0.55])
        box.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (-1, -1), PANEL),
                                 ("BOX", (0, 0), (-1, -1), 0.6, RULE), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                                 ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        flow.append(box)
        if pre.get("warning"):
            flow.append(Spacer(1, 2 * mm))
            flow.append(_boxed([[Paragraph(f"<b>{_escape(pre['warning'])}</b>", st["body"])]],
                               background=colors.HexColor("#fbe9e7"), border=colors.HexColor("#b3261e")))
        flow.append(Paragraph(f"Model: {_escape(model.get('encoder', ''))} multi-task U-Net, checkpoint epoch "
                              f"{model.get('epoch')}, trained on {_escape(', '.join(model.get('trained_on') or []))}. "
                              "Requires confirmation by a qualified pathologist.", st["small"]))
    elif pre.get("available"):
        reasons = "".join(f"<br/>&bull; {_escape(r)}" for r in pre.get("withheld_reasons", []))
        flow.append(_boxed([[Paragraph("<b>AI pre-score withheld at this site.</b> The model is not yet locally validated "
                                       "here; its output is logged for validation and not shown." + reasons, st["body"])]]))
    else:
        flow.append(_boxed([[Paragraph("No AI pre-score model loaded: measured evidence only.", st["body"])]]))
    flow.append(Spacer(1, 4 * mm))

    # --- ISH guidance ----------------------------------------------------------
    if guide:
        ish = guide.get("ish", {})
        label, fg, bg = ISH_STYLE.get(ish.get("level"), ISH_STYLE["not_applicable"])
        body = [Paragraph(f'<font color="{fg}"><b>{label}</b></font> &nbsp; <font color="#5b6270">'
                          f'({_escape(guide.get("suggested_range", ""))}; basis: {_escape(guide.get("basis", ""))})</font>', st["body"]),
                Paragraph(_escape(ish.get("text", "")), st["body"])]
        if guide.get("cautions"):
            body.append(Paragraph("<b>Cautions</b>" + "".join(f"<br/>&bull; {_escape(c)}" for c in guide["cautions"]), st["body"]))
        if guide.get("next_steps"):
            body.append(Paragraph("<b>Suggested next steps</b>" + "".join(f"<br/>&bull; {_escape(c)}" for c in guide["next_steps"]), st["body"]))
        flow.append(KeepTogether([Paragraph("Suggested next steps (for the pathologist's decision)", st["h"]),
                                  _boxed([[b] for b in body], background=colors.HexColor(bg), border=colors.HexColor(fg))]))
    flow.append(Spacer(1, 3 * mm))

    # --- cell evidence -------------------------------------------------------
    if cells:
        pct = cells.get("percent", {})
        data = [["Cells measured", "IHC 0", "1+ (faint, incomplete)", "2+ (complete, weak-mod.)", "3+ (complete, intense)"],
                [str(cells.get("cells_measured", 0))] + [f"{pct.get(g, 0):.1f}%" for g in ("0", "1+", "2+", "3+")]]
        flow.append(Paragraph("Cell-level ASCO/CAP evidence", st["h"]))
        flow.append(_grid(data, [28 * mm, 22 * mm, 40 * mm, 44 * mm, 42 * mm]))
        notes = [f"Field category by the ASCO/CAP 10% rule: <b>IHC {cells.get('field_category')}</b> -- {_escape(cells.get('rule_applied', ''))}."]
        if cells.get("her2_low"):
            notes.append("HER2-low range (1+).")
        if cells.get("her2_ultralow"):
            notes.append("Faint incomplete staining in >0% and <=10% of cells (HER2-ultralow range).")
        for f in cells.get("flags", []):
            notes.append(f"&#9888; {_escape(f)}")
        flow.append(Paragraph(" ".join(notes), st["small"]))
    flow.append(Spacer(1, 4 * mm))

    # --- pathologist confirmation ------------------------------------------
    box = "[&nbsp;&nbsp;]"  # Helvetica has no empty-box glyph; a filled square would read as already ticked
    rows = [[Paragraph("<b>Pathologist confirmation</b> (completed by the reporting pathologist)", st["body"])],
            [Paragraph(f"Final IHC score: {box} 0 &nbsp; {box} ultralow &nbsp; {box} 1+ &nbsp; {box} 2+ &nbsp; {box} 3+ "
                       f"&nbsp;&nbsp;&nbsp; Agrees with AI pre-score: {box} yes {box} no", st["body"])],
            [Paragraph(f"ISH ordered: {box} yes {box} no &nbsp;&nbsp;&nbsp; Control tissue acceptable: {box} yes {box} no "
                       f"&nbsp;&nbsp;&nbsp; Invasive tumour present: {box} yes {box} no", st["body"])],
            [Paragraph("Comments: ________________________________________________________________________________", st["body"])],
            [Paragraph("Pathologist: ______________________________ &nbsp; Signature: ____________________ &nbsp; Date: ____________", st["body"])]]
    flow.append(KeepTogether(_boxed(rows, background=colors.white, border=INK)))
    return flow


QC_MARK = {"ok": ("OK", "#1e6b45"), "warn": ("CHECK", "#9a5b00"), "fail": ("FAIL", "#b3261e"), "info": ("NOTE", "#5b6270")}
WEIGHT_COLORS = {"decisive": "#b3261e", "strong": "#c25e00", "moderate": "#9a5b00", "supporting": "#1e6b45", "minor": "#5b6270"}


def _decision_page(a: dict, st) -> list:
    """ISH decision support and the explainable-AI evidence (app/decision.py, app/explain.py)."""
    cells = a.get("cell_evidence") or {}
    dec = cells.get("decision_support")
    exp = cells.get("explanation")
    if not dec and not exp:
        return []
    flow = [Paragraph("ISH decision support and explainable AI", st["title"]),
            Paragraph("The evidence behind the suggestion, in the order the ISH decision is made. Every figure is "
                      "measured on this field; the pathologist decides.", st["small"]), Spacer(1, 2 * mm)]
    guide = a.get("guidance") or {}
    ish = guide.get("ish") or {}
    if dec:
        label, fg, bg = ISH_STYLE.get(ish.get("level"), ISH_STYLE["not_applicable"])
        flow.append(_boxed([[Paragraph(f"<font color='{fg}'><b>{label}</b></font>  {_escape(ish.get('text', ''))}"
                                       f"<br/><font size=7.5 color='#5b6270'>Basis: {_escape(dec.get('basis'))}. "
                                       "The pathologist decides.</font>", st["body"])]],
                           background=colors.HexColor(bg), border=colors.HexColor(fg)))
        flow.append(Paragraph("ASCO/CAP algorithm: where this case sits", st["h"]))
        data = [["IHC", "Result", "Action"]]
        taken = 0
        for i, s_ in enumerate(dec.get("pathway") or []):
            data.append([("> " if s_["taken"] else "") + s_["grade"], Paragraph(_escape(s_["result"]), st["small"]),
                         Paragraph(_escape(s_["action"]), st["small"])])
            if s_["taken"]:
                taken = i + 1
        t = _grid(data, [16 * mm, 42 * mm, CONTENT_WIDTH - 58 * mm], align_right_from=9)
        if taken:
            t.setStyle(TableStyle([("BACKGROUND", (0, taken), (-1, taken), colors.HexColor("#fff3d6")),
                                   ("FONTNAME", (0, taken), (0, taken), "Helvetica-Bold")]))
        flow.append(t)

        def ev(items):
            if not items:
                return [Paragraph("None.", st["small"])]
            return [Paragraph(f"<font color='{WEIGHT_COLORS.get(e['weight'], '#5b6270')}'><b>{e['weight'].upper()}</b></font> "
                              f"{_escape(e['text'])}", st["small"]) for e in items]
        flow.append(Paragraph("Evidence for and against ISH", st["h"]))
        t = Table([[Paragraph("<b>For ISH</b>", st["body"]), Paragraph("<b>Against ISH</b>", st["body"])],
                   [ev(dec.get("evidence_for_ish")), ev(dec.get("evidence_against_ish"))]],
                  colWidths=[CONTENT_WIDTH / 2] * 2, hAlign="LEFT")
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9edf2"))]))
        flow.append(t)
        if dec.get("her2_low_boundary"):
            flow.append(Spacer(1, 1.5 * mm))
            flow.append(_boxed([[Paragraph(f"<b>HER2-0 vs HER2-low:</b> {_escape(dec['her2_low_boundary'])}", st["small"])]],
                               background=colors.HexColor("#fff6e5"), border=colors.HexColor("#e0a040")))

        flow.append(Paragraph("Can this field be trusted? Quality checklist", st["h"]))
        data = [["", "Check", "Finding"]]
        marks = []
        for q in dec.get("qc") or []:
            text, colour = QC_MARK.get(q["status"], QC_MARK["info"])
            data.append([text, q["check"], Paragraph(_escape(q["detail"]), st["small"])])
            marks.append(colour)
        t = _grid(data, [16 * mm, 44 * mm, CONTENT_WIDTH - 60 * mm], align_right_from=9)
        t.setStyle(TableStyle([("TEXTCOLOR", (0, i + 1), (0, i + 1), colors.HexColor(c)) for i, c in enumerate(marks)]
                              + [("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold")]))
        flow.append(t)

        flow.append(Paragraph("How close is it to the 10% cut-off? (95% Wilson confidence intervals)", st["h"]))
        data = [["Measure", "Share", "95% interval", "Reading"]]
        for c in dec.get("certainty") or []:
            data.append([c["measure"], f"{c['share']:.1f}%", f"{c['low']:.1f}-{c['high']:.1f}%",
                         Paragraph(("<font color='#b3261e'><b>" if c.get("near") else "") + _escape(c["reading"])
                                   + ("</b></font>" if c.get("near") else ""), st["small"])])
        flow.append(_grid(data, [64 * mm, 18 * mm, 28 * mm, CONTENT_WIDTH - 110 * mm]))
        rob = dec.get("robustness") or {}
        if rob.get("runs"):
            spread = ", ".join(f"{g}: {v}" for g, v in rob["by_grade"].items() if v)
            flow.append(Paragraph(f"<b>Robustness:</b> {rob['stable_percent']}% of {rob['runs']} nearby readings keep "
                                  f"IHC {rob['baseline_grade']} ({spread}); each cell re-scored with the faint cut "
                                  "+/-15%, the strong cut +/-10% and the completeness rule +/-0.10.", st["body"]))
        for w in dec.get("what_if") or []:
            flow.append(Paragraph(f"&bull; {_escape(w)}", st["body"]))

        targets = dec.get("ish_targets") or []
        if targets:
            heading = Paragraph("Where to score ISH (highest-grade, highest-weight regions)", st["h"])
            row = [[_data_uri_to_image(r["image"], 300, width=48 * mm),
                    Paragraph(f"Region row {r['row']}, col {r['col']}: <b>{r['grade']}</b>, {r['weight']}% weight", st["small"])]
                   for r in targets]
            t = Table([row], colWidths=[CONTENT_WIDTH / 3] * len(row), hAlign="LEFT")
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
            flow.append(KeepTogether([heading, t]))  # never a heading stranded above its images

    if exp:
        flow.append(CondPageBreak(90 * mm))  # continue on the same page when there is room
        flow.append(Paragraph("Why this result: explained", st["title"]))
        for i, step in enumerate(exp.get("steps") or [], 1):
            flow.append(Paragraph(f"<b>{i}. {_escape(step['title'])}</b>", st["body"]))
            flow.append(Paragraph(_escape(step["text"]), st["body"]))
            flow.append(Spacer(1, 1.2 * mm))
        flow.append(Paragraph("ASCO/CAP criteria check (cell measurements)", st["h"]))
        data = [["IHC", "ASCO/CAP definition", "Measured", "Met"]]
        met_row = 0
        for i, c in enumerate(exp.get("criteria") or [], 1):
            data.append([c["grade"], Paragraph(_escape(c["definition"]), st["small"]), f"{c['measured']:.1f}%",
                         "yes" if c["met"] else "-"])
            if c["met"]:
                met_row = i
        t = _grid(data, [14 * mm, CONTENT_WIDTH - 50 * mm, 20 * mm, 16 * mm], align_right_from=2)
        if met_row:
            t.setStyle(TableStyle([("BACKGROUND", (0, met_row), (-1, met_row), colors.HexColor("#e3f2e8"))]))
        flow.append(t)
        examples = exp.get("examples") or {}
        if any(examples.values()):
            flow.append(Paragraph("Example cells from this field (the coloured line is the membrane ring that was measured)", st["h"]))
            names = {"3+": "3+ complete, intense", "2+": "2+ complete, weak-moderate", "1+": "1+ faint, incomplete",
                     "0": "0 no membrane staining"}
            for g in ("3+", "2+", "1+", "0"):
                items = examples.get(g) or []
                if not items:
                    continue
                cells_row = [Paragraph(f"<font color='{GRADE_COLORS[g]}'><b>{names[g]}</b></font>", st["small"])]
                for e in items[:4]:
                    cells_row.append([_data_uri_to_image(e["image"], 160, width=26 * mm),
                                      Paragraph(f"{e['completeness']}% ring, {e['level']}", st["label"])])
                while len(cells_row) < 5:
                    cells_row.append("")
                t = Table([cells_row], colWidths=[34 * mm] + [36 * mm] * 4, hAlign="LEFT")
                t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                       ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
                flow.append(t)
        for d in exp.get("definitions") or []:
            flow.append(Paragraph(f"<b>{_escape(d['term'])}.</b> {_escape(d['text'])}", st["small"]))
            flow.append(Spacer(1, 0.8 * mm))
    if dec and dec.get("ish_groups"):
        flow.append(Paragraph("Reading the ISH result (ASCO/CAP 2018 dual-probe groups)", st["h"]))
        data = [["Group", "Criteria", "Result"]]
        for g in dec["ish_groups"]:
            data.append([g["group"], Paragraph(_escape(g["criteria"]), st["small"]), Paragraph(_escape(g["result"]), st["small"])])
        flow.append(_grid(data, [14 * mm, 70 * mm, CONTENT_WIDTH - 84 * mm], align_right_from=9))
    return flow


def _explanation_page(a: dict, st) -> list:
    flow = [Paragraph("Visual explanation", st["title"]),
            Paragraph("What the system looked at, and why. Each panel answers one question.", st["small"]), Spacer(1, 3 * mm)]
    images = a.get("images") or {}
    cells = []
    for key in ("original", "cells", "evidence", "regions", "model", "heatmap", "baseline", "ambiguity"):
        if key in images:
            title, caption = PANEL_TITLES[key]
            cells.append([Paragraph(f"<b>{title}</b>", st["body"]), _data_uri_to_image(images[key]), Paragraph(caption, st["small"])])
    rows = [cells[i:i + 2] for i in range(0, len(cells), 2)]
    if rows and len(rows[-1]) == 1:
        rows[-1].append("")
    if rows:
        t = Table(rows, colWidths=[CONTENT_WIDTH / 2] * 2, hAlign="LEFT")
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        flow.append(t)
    regions = ((a.get("ai_prescore") or {}).get("prescore") or {}).get("regions") or []
    if regions:
        flow.append(Paragraph("Regional pre-scores", st["h"]))
        data = [["Region (row, col)", "Pre-score", "P(0)", "P(1+)", "P(2+)", "P(3+)", "Weight in overall", "Tissue"]]
        for g in regions:
            pr = g["probabilities"]
            data.append([f"{g['row'] + 1}, {g['col'] + 1}", g["category"]] + [f"{pr[k]:.0%}" for k in ("0", "1+", "2+", "3+")]
                        + [f"{g['attention']:.0%}", f"{g['tissue_fraction']:.0%}"])
        flow.append(_grid(data, [28 * mm, 20 * mm, 16 * mm, 16 * mm, 16 * mm, 16 * mm, 30 * mm, 18 * mm]))
    return flow


def _cell_method_text() -> str:
    """Cell-evidence method line, with the held-out agreement read from the calibration file (never hard-coded)."""
    import json

    text = ("<b>Cell evidence</b>: nuclei from colour deconvolution, cell territories grown to neighbouring cells, membrane "
            "DAB measured around each circumference (completeness and intensity), ASCO/CAP 10% rule.")
    path = Path(__file__).resolve().parents[1] / "configs" / "cell_params.json"
    try:
        cal = json.loads(path.read_text(encoding="utf-8")).get("calibration", {})
        conf = cal.get("holdout_confusion")
        recall = [row[i] / max(1, sum(row)) for i, row in enumerate(conf)] if conf else None
        text += (f" Cut points calibrated on {cal['fit_patches']} training patches; on {cal['holdout_patches']} holdout patches the "
                 f"field category agreed with the patch label in {cal['holdout_accuracy']:.0%} (kappa {cal['holdout_qwk']:.3f})")
        if recall:
            text += f", recall 0 / 1+ / 2+ / 3+ = {' / '.join(f'{r:.0%}' for r in recall)}"
        text += "."
    except (OSError, ValueError, KeyError):
        text += " (Calibration record not found.)"
    return text


def _methods_page(a: dict, st) -> list:
    flow = [Paragraph("Measurements, method and limitations", st["title"]), Spacer(1, 2 * mm)]
    model_pct = a.get("model_percentages") or {}
    base_pct = a.get("baseline_percentages") or {}
    if model_pct or base_pct:
        flow.append(Paragraph("Stained area, as a percentage of detected tissue", st["h"]))
        data = [["Intensity class", "Model", "Threshold baseline", "Difference"]]
        order = ["negative", "weak (1+)", "moderate (2+)", "strong (3+)"]
        names = [n for n in order if n in model_pct or n in base_pct] + sorted(
            (set(model_pct) | set(base_pct)) - set(order))
        for name in names:
            m, b = model_pct.get(name, 0.0), base_pct.get(name, 0.0)
            data.append([name, f"{m:.2f}%", f"{b:.2f}%", f"{m - b:+.2f} pp"])
        unclassified = a.get("model_unclassified_percent")
        if unclassified:
            data.append(["not classified by the model", f"{unclassified:.2f}%", "0.00%", ""])
        flow.append(_grid(data, [60 * mm, 30 * mm, 40 * mm, 30 * mm]))
        flow.append(Paragraph("Tissue-area percentages are not tumour-cell percentages; the cell-level table on page 1 is "
                              "the ASCO/CAP-aligned measurement.", st["small"]))
    flow.append(Paragraph("How this report was produced", st["h"]))
    for line in (
        "<b>AI pre-score</b>: a ResNet-50 U-Net with a HER2 score head and attention pooling over 512 px regions, trained on "
        "HER2_IHC_40X and BCI. On 1,904 reserved holdout patches from its training site: 92.3% accuracy, quadratic-weighted "
        "kappa 0.975. At hospitals it has not been validated on, accuracy was measured as low as 48%, which is why the site "
        "safety gate withholds the pre-score until local validation.",
        _cell_method_text(),
        "<b>Explanations</b>: Grad-CAM evidence for the predicted grade; per-region pre-scores from the same score head; "
        "attention weights showing each region's contribution.",
        "<b>ISH guidance</b>: ASCO/CAP 2018 algorithm (affirmed 2023): 2+ requires reflex ISH; 3+ does not; 0/1+ are negative "
        "with HER2-low/ultralow noted. Extra cautions push toward ISH or a second review.",
    ):
        flow.append(Paragraph(line, st["body"]))
        flow.append(Spacer(1, 1.5 * mm))
    flow.append(Paragraph("Limitations", st["h"]))
    for text in (a.get("caveats") or {}).values():
        flow.append(Paragraph(f"&bull; {_escape(text)}", st["small"]))
        flow.append(Spacer(1, 1 * mm))
    flow.append(Spacer(1, 4 * mm))
    flow.append(Paragraph(REPORT_FOOTER, st["small"]))
    return flow


def _render(analysis_dict: dict, target, title_for: str) -> None:
    st = _styles()
    doc = SimpleDocTemplate(target, pagesize=A4, leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN,
                            topMargin=PAGE_MARGIN, bottomMargin=PAGE_MARGIN, title=f"BioMarkHER2 -- {title_for}")

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(PAGE_MARGIN, 8 * mm, f"BioMarkHER2 pre-scoring report -- {title_for[:60]}")
        canvas.drawRightString(A4[0] - PAGE_MARGIN, 8 * mm, f"page {doc_.page} -- AI suggestions require pathologist confirmation")
        canvas.restoreState()

    decision = _decision_page(analysis_dict, st)
    flow = (_summary_page(analysis_dict, st) + [PageBreak()] + (decision + [PageBreak()] if decision else [])
            + _explanation_page(analysis_dict, st) + [PageBreak()] + _methods_page(analysis_dict, st))
    doc.build(flow, onFirstPage=footer, onLaterPages=footer)
