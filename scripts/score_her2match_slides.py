"""Run the whole-slide analysis (the same SlideAnalyzer the Slides page uses) on the HER2match test slides
and compare the AI pre-score and cell evidence with each slide's pathologist score.

    python scripts/score_her2match_slides.py [--root data/slides/HER2match] [--max-fields 40]

HER2match (Zenodo 10.5281/zenodo.15797050, CC BY-NC-SA 4.0) is an UNVALIDATED site for this model (3DHistech
P1000 scanner, 0.25 um/px), so pre-scores are produced in research mode only and must not inform patient care.
Writes artifacts/her2match_slide_scores.json and prints a table.
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
from app.server import build_argparser, build_site_policy  # noqa: E402
from wsi.analysis import SlideAnalyzer, SlideSettings  # noqa: E402
from wsi.reader import Slide  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default="data/slides/HER2match")
    p.add_argument("--max-fields", type=int, default=40)
    p.add_argument("--out", default="artifacts/her2match_slide_scores.json")
    p.add_argument("--prescore-run", default=None, help="pre-score checkpoint (default: the server default)")
    p.add_argument("--stain-profile", default=None, help="FILE:KEY, see app/server.py --stain-profile")
    p.add_argument("--only", nargs="*", default=None, help="slide file stems to score, e.g. 002 016 (default: all)")
    p.add_argument("--regions", default=None, help="JSON file {slide file name: [{x,y,w,h}, ...]} of marked tumour")
    own = p.parse_args()

    args = build_argparser().parse_args(["--site-name", "HER2match (3DHistech P1000)", "--site-mpp", "0.25",
                                         "--research-prescores"])
    policy = build_site_policy(args)
    from app.server import load_stain_profile

    analyzer = Analyzer(args.run, args.config, args.preprocessing, args.conformal_alpha,
                        prescore_checkpoint=own.prescore_run or args.prescore_run,
                        prescore_site_norm=load_stain_profile(own.stain_profile), site_policy=policy, shadow_log=None)
    regions = json.loads(Path(own.regions).read_text()) if own.regions else {}
    analyzer.control_level, analyzer.control_reference, analyzer.learning = None, None, None
    sa = SlideAnalyzer(analyzer, SlideSettings(max_fields=own.max_fields))

    rows = []
    from wsi.reader import SLIDE_SUFFIXES

    paths = [p for p in Path(own.root).rglob("*") if p.is_file() and p.suffix.lower() in SLIDE_SUFFIXES]
    if own.only:
        paths = [p for p in paths if p.stem in set(own.only)]
    for path in sorted(paths):
        truth = path.parent.name.replace("score_", "").replace("plus", "+")
        t = time.time()
        try:
            res = sa.run(Slide(path), regions=regions.get(path.name))
        except Exception as e:  # incomplete download, unreadable file
            print(f"{path.name}: FAILED ({e})")
            rows.append({"slide": path.name, "truth": truth, "error": str(e)})
            continue
        block = res.get("ai_prescore") or {}
        pre = block.get("prescore") or {}
        ce = res["cell_evidence"]
        primary = res.get("primary_score") or {}
        row = {"slide": path.name, "truth": truth, "ai_prescore": pre.get("category"),
               "ai_probabilities": pre.get("probabilities"), "heterogeneity": (pre.get("heterogeneity") or {}).get("fields_by_grade"),
               # the call the portal shows: the cell-level ASCO/CAP rule, with the AI as second opinion
               "primary_category": primary.get("category"), "primary_unavailable": primary.get("unavailable_reasons"),
               "cell_category": ce.get("measured_category") or ce.get("field_category"),
               "cells_measured": ce.get("cells_measured"),
               "cell_percentages": {"by_grade": ce.get("percent"), "at_least_1plus": ce.get("percent_at_least_1plus"),
                                    "at_least_2plus": ce.get("percent_at_least_2plus")},
               "ish_level": (res.get("guidance") or {}).get("ish", {}).get("level"),
               "focal_2plus_fields": len(primary.get("focal_2plus_fields") or []),
               "field_cell_categories": [f.get("cell_category") for f in res.get("fields") or []],
               "field_cells": [f.get("cells") for f in res.get("fields") or []],
               "field_2plus_pct": [f.get("cells_at_least_2plus_pct") for f in res.get("fields") or []],
               "field_ai_categories": [f.get("prescore_category") for f in res.get("fields") or []],
               "fields": res["tissue"]["fields_selected"], "rejected_fields": len(res["rejected_fields"]),
               "flags": res.get("flags") or [], "seconds": round(time.time() - t)}
        rows.append(row)
        print(f"{path.name:10s} truth {truth:3s} | primary {row['primary_category']} | AI {row['ai_prescore']} {row['ai_probabilities']} | "
              f"cells {row['cell_category']} {row['cell_percentages']} | ISH {row['ish_level']} (focal {row['focal_2plus_fields']}) | fields {row['fields']} ({row['rejected_fields']} rejected) | {row['seconds']}s",
              flush=True)
    Path(own.out).parent.mkdir(parents=True, exist_ok=True)
    Path(own.out).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"wrote {own.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
