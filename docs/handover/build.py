"""Build the SDC handover documents: Markdown -> HTML -> PDF (headless Chrome) and DOCX (Microsoft Word).

    python docs/handover/build.py --out dist/handover_docs [--no-docx]

Each NN_Name.md becomes NN_Name.pdf and NN_Name.docx. Front matter (title, subtitle, doc_id) sets the cover line and
the page footer. Images are referenced as img/<file>.png. DOCX needs Word (Windows, COM via PowerShell).
"""
from __future__ import annotations

import argparse
import base64
import re
import subprocess
import sys
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
RELEASE = "sdc-2026.11.11"
DATE = "11 November 2026"

CSS = """
:root { --ink:#1f2937; --muted:#6b7280; --rule:#d1d5db; --accent:#4338ca; --tint:#eef2ff; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", Arial, sans-serif; color: var(--ink); font-size: 10.5pt; line-height: 1.5; margin: 0; }
.cover { border-bottom: 3px solid var(--accent); padding-bottom: 10px; margin-bottom: 18px; }
.cover .brand { color: var(--accent); font-weight: 700; letter-spacing: .04em; font-size: 9pt; text-transform: uppercase; }
.cover .sub { color: var(--muted); font-size: 11pt; margin-top: 2px; }
h1 { font-size: 22pt; margin: 4px 0 2px; color: #111827; }
h2 { font-size: 14.5pt; margin: 22px 0 8px; padding-top: 6px; border-top: 1px solid var(--rule); color: #111827; page-break-after: avoid; }
h3 { font-size: 11.5pt; margin: 16px 0 6px; color: #111827; page-break-after: avoid; }
p, li { orphans: 3; widows: 3; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 12px; font-size: 9.3pt; page-break-inside: auto; }
tr { page-break-inside: avoid; }
th, td { border: 1px solid var(--rule); padding: 4px 7px; vertical-align: top; text-align: left; }
th { background: #f3f4f6; font-weight: 600; }
code { font-family: Consolas, "Courier New", monospace; font-size: 8.8pt; background: #f3f4f6; padding: 0 3px; border-radius: 3px; }
pre { background: #f8fafc; border: 1px solid var(--rule); border-radius: 6px; padding: 8px 10px; font-size: 8.4pt;
      line-height: 1.4; white-space: pre-wrap; word-break: break-word; page-break-inside: avoid; }
pre code { background: none; padding: 0; font-size: inherit; }
blockquote { margin: 10px 0; padding: 8px 12px; background: #fffbeb; border-left: 4px solid #f59e0b; }
blockquote p { margin: 0; }
img { max-width: 100%; border: 1px solid var(--rule); border-radius: 4px; display: block; margin: 6px auto 2px; }
p > img:only-child { page-break-inside: avoid; }
.caption { text-align: center; color: var(--muted); font-size: 8.8pt; margin: 0 0 12px; }
figure { margin: 8px 0 14px; page-break-inside: avoid; }
figure svg { width: 100%; height: auto; }
figcaption { text-align: center; color: var(--muted); font-size: 8.8pt; }
"""


def front_matter(text: str) -> tuple[dict, str]:
    meta = {}
    if text.startswith("---"):
        head, body = text[3:].split("\n---", 1)
        for line in head.strip().splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
        text = body.lstrip("\n")
    return meta, text


def to_html(md_path: Path, svg_as_png: dict[str, str] | None = None) -> tuple[dict, str]:
    meta, text = front_matter(md_path.read_text(encoding="utf-8"))
    # The first H1 is replaced by the cover block.
    text = re.sub(r"^# .*\n", "", text, count=1, flags=re.M)
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists", "attr_list", "md_in_html"])
    # Each image gets a caption from its alt text.
    body = re.sub(r'<p><img alt="([^"]*)" src="([^"]+)" ?/?></p>',
                  lambda m: f'<p><img alt="{m[1]}" src="{m[2]}"></p><p class="caption">{m[1]}</p>', body)
    if svg_as_png:
        for i, (svg, png) in enumerate(svg_as_png.items()):
            body = body.replace(svg, f'<img src="{png}" style="border:none">')
    cover = (f'<div class="cover"><div class="brand">BioMarkHER2 · Handover to SDC · {meta.get("doc_id", "")}</div>'
             f'<h1>{meta.get("title", md_path.stem)}</h1><div class="sub">{meta.get("subtitle", "")}</div></div>')
    html = (f'<!doctype html><html><head><meta charset="utf-8"><title>{meta.get("title", "")}</title>'
            f"<style>{CSS}</style></head><body>{cover}{body}</body></html>")
    return meta, html


def footer(meta: dict) -> str:
    return ('<div style="font-size:7.5pt;color:#6b7280;width:100%;padding:0 14mm;display:flex;justify-content:space-between;'
            'font-family:Segoe UI,Arial,sans-serif">'
            f'<span>BioMarkHER2 · {meta.get("title", "")} · {meta.get("doc_id", "")} · release {RELEASE} · {DATE}</span>'
            '<span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>')


def word_convert(html_files: list[Path]) -> None:
    """HTML -> DOCX through Word, embedding (not linking) every picture."""
    lines = ["$ErrorActionPreference = 'Stop'", "$w = New-Object -ComObject Word.Application", "$w.Visible = $false"]
    for h in html_files:
        d = h.with_suffix(".docx")
        lines += [
            f"$doc = $w.Documents.Open('{h}', $false, $true)",
            "foreach ($s in $doc.InlineShapes) { if ($s.LinkFormat) { $s.LinkFormat.SavePictureWithDocument = $true; $s.LinkFormat.BreakLink() } }",
            "$doc.PageSetup.TopMargin = 54; $doc.PageSetup.BottomMargin = 54; $doc.PageSetup.LeftMargin = 54; $doc.PageSetup.RightMargin = 54",
            # Word ignores CSS max-width: fit every picture to the text width, keeping its proportions.
            "$max = $doc.PageSetup.PageWidth - $doc.PageSetup.LeftMargin - $doc.PageSetup.RightMargin",
            "foreach ($s in $doc.InlineShapes) { $s.LockAspectRatio = -1; if ($s.Width -gt $max) { $s.Width = $max } }",
            "foreach ($t in $doc.Tables) { $t.Borders.Enable = 1 }",
            f"$doc.SaveAs2('{d}', 16)",
            "$doc.Close($false)",
        ]
    lines.append("$w.Quit()")
    subprocess.run(["powershell", "-NoProfile", "-Command", "\n".join(lines)], check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist/handover_docs")
    ap.add_argument("--no-docx", action="store_true")
    a = ap.parse_args()
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "img").mkdir(exist_ok=True)
    for img in (HERE / "img").glob("*.png"):
        (out / "img" / img.name).write_bytes(img.read_bytes())

    sources = sorted(HERE.glob("[0-9][0-9]_*.md"))
    html_for_word = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        for md in sources:
            meta, html = to_html(md)
            html_path = out / f"{md.stem}.html"
            html_path.write_text(html, encoding="utf-8")
            page.goto(html_path.as_uri(), wait_until="load")
            page.pdf(path=str(out / f"{md.stem}.pdf"), format="A4", print_background=True,
                     margin={"top": "16mm", "bottom": "18mm", "left": "14mm", "right": "14mm"},
                     display_header_footer=True, header_template="<span></span>", footer_template=footer(meta))
            print("pdf ", md.stem, flush=True)
            # Word cannot draw inline SVG: render each figure to PNG for the DOCX copy.
            svgs = {}
            for k, svg in enumerate(page.locator("figure svg").all()):
                png = f"img/{md.stem}_fig{k + 1}.png"
                svg.screenshot(path=str(out / png))
                svgs[svg.evaluate("e => e.outerHTML")] = png
            if svgs:
                _, html = to_html(md)
                for outer, png in svgs.items():
                    html = re.sub(r"<svg.*?</svg>", f'<img src="{png}" style="border:none">', html, count=1, flags=re.S)
            word_html = out / f"{md.stem}.word.html"
            word_html.write_text(html.replace("display: flex", "display: block"), encoding="utf-8")
            html_for_word.append(word_html)
        browser.close()
    if not a.no_docx:
        word_convert(html_for_word)
        for h in html_for_word:
            h.with_suffix(".docx").replace(out / (h.name.replace(".word.html", ".docx")))
            print("docx", h.stem.replace(".word", ""), flush=True)
    for h in html_for_word:
        h.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
