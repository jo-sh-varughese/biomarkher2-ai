"""Run the whole-slide analysis (the same SlideAnalyzer the Slides page uses) on the K-DISC slides and save
what it found per slide: the cell-level pre-score, the AI field grades, ISH guidance, rejected fields and flags.

    python scripts/score_kdisc_slides.py [--root "kdisc data set/HER2_Tiff"] [--max-fields 40]

K-DISC (Medprime scanner, 0.286 um/px) is an UNVALIDATED site for this model, and the slides come without a
pathologist's reference score, so this reports what the system called and why -- not an accuracy.
Writes artifacts/kdisc_slide_scores.json and prints one line per slide.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.analysis import Analyzer  # noqa: E402
from app.server import build_argparser, build_site_policy, load_stain_profile  # noqa: E402
from wsi.analysis import SlideAnalyzer, SlideSettings  # noqa: E402
from wsi.reader import SLIDE_SUFFIXES, Slide  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default="kdisc data set/HER2_Tiff")
    p.add_argument("--max-fields", type=int, default=40)
    p.add_argument("--out", default="artifacts/kdisc_slide_scores.json")
    own = p.parse_args()

    args = build_argparser().parse_args(["--site-name", "K-DISC (Medprime)", "--research-prescores"])
    analyzer = Analyzer(args.run, args.config, args.preprocessing, args.conformal_alpha,
                        prescore_checkpoint=args.prescore_run, prescore_site_norm=load_stain_profile(None),
                        site_policy=build_site_policy(args), shadow_log=None)
    analyzer.control_level, analyzer.control_reference, analyzer.learning = None, None, None
    sa = SlideAnalyzer(analyzer, SlideSettings(max_fields=own.max_fields))

    rows = []
    for path in sorted(q for q in Path(own.root).rglob("*") if q.is_file() and q.suffix.lower() in SLIDE_SUFFIXES):
        t = time.time()
        try:
            slide = Slide(path)
            res = sa.run(slide)
        except Exception as e:  # unreadable or incomplete file
            print(f"{path.name}: FAILED ({type(e).__name__}: {e})", flush=True)
            rows.append({"slide": path.name, "error": f"{type(e).__name__}: {e}"})
            continue
        ce = res["cell_evidence"]
        primary = res.get("primary_score") or {}
        fields = res.get("fields") or []
        row = {
            "slide": path.name, "info": slide.info.to_dict(), "seconds": round(time.time() - t),
            "primary_category": primary.get("category"), "primary_unavailable": primary.get("unavailable_reasons"),
            "cell_category": ce.get("measured_category") or ce.get("field_category"), "cells_measured": ce.get("cells_measured"),
            "cell_percent": ce.get("percent"), "pct_ge_2plus": ce.get("percent_at_least_2plus"),
            "ish_level": (res.get("guidance") or {}).get("ish", {}).get("level"),
            "fields_selected": res["tissue"].get("fields_selected"), "rejected_fields": len(res.get("rejected_fields") or []),
            "field_cell_categories": [f.get("cell_category") for f in fields],
            "field_ai_categories": [f.get("prescore_category") for f in fields],
            "flags": res.get("flags") or [],
        }
        rows.append(row)
        agree = sum(c == a for c, a in zip(row["field_cell_categories"], row["field_ai_categories"]))
        print(f"{path.name} | {row['primary_category'] or 'not assessable'} | cells {row['cells_measured']} "
              f">=2+ {row['pct_ge_2plus']} | fields {row['fields_selected']} ({row['rejected_fields']} rejected) | "
              f"AI = cell rule on {agree}/{len(fields)} fields | ISH {row['ish_level']} | {row['seconds']}s", flush=True)
    Path(own.out).parent.mkdir(parents=True, exist_ok=True)
    Path(own.out).write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    print(f"wrote {own.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
