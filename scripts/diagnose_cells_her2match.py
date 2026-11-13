"""Per-cell diagnosis of the HER2match slides: why is the 2+ slide (025) scored 0 by the cell rule?

    python scripts/diagnose_cells_her2match.py [--regions artifacts/her2match_test_regions.json]

Runs the real slide pipeline (wsi/analysis.py, the same fields and cell measurement the portal uses),
inside the marked tumour regions, and keeps every cell's raw membrane read-out (24 per-sector DAB maxima,
cytoplasmic DAB). Writes artifacts/cell_diagnosis/<slide>.npz plus a few field images with cell overlays,
then (step 2) asks whether ANY single set of cut points sorts all four slides correctly.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

OUT = ROOT / "artifacts" / "cell_diagnosis"
SLIDES = {"HER2match_016.tiff": 0, "HER2match_015.tiff": 1, "HER2match_025.tiff": 2, "HER2match_013.tiff": 3}


def collect(regions_file: str) -> None:
    import app.cells as cells_mod
    from app.analysis import Analyzer
    from app.server import build_argparser, build_site_policy
    from wsi.analysis import SlideAnalyzer, SlideSettings
    from wsi.reader import Slide

    args = build_argparser().parse_args(["--site-name", "HER2match", "--site-mpp", "0.25", "--research-prescores"])
    an = Analyzer(args.run, args.config, args.preprocessing, args.conformal_alpha, prescore_checkpoint=args.prescore_run,
                  site_policy=build_site_policy(args), shadow_log=None)
    an.control_level, an.control_reference, an.learning = None, None, None
    regions = json.loads(Path(regions_file).read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    original = cells_mod.analyze_cells
    for name in SLIDES:
        path = next((ROOT / "data/slides/HER2match_tiff").rglob(name))
        captured = []

        def spy(rgb, tissue, thresholds, params=None):
            res = original(rgb, tissue, thresholds, params)
            captured.append((rgb, res))
            return res

        cells_mod.analyze_cells = spy
        try:
            out = SlideAnalyzer(an, SlideSettings(max_fields=40)).run(Slide(path), regions=regions.get(name))
        finally:
            cells_mod.analyze_cells = original
        sectors, cyto, field = [], [], []
        for i, (rgb, res) in enumerate(captured):
            for r in res["cells"]:
                sectors.append(r["sector_max"])
                cyto.append(r["cytoplasm_od"])
                field.append(i)
        np.savez_compressed(OUT / f"{path.stem}.npz", sectors=np.array(sectors, dtype=np.float32),
                            cyto=np.array(cyto, dtype=np.float32), field=np.array(field, dtype=np.int16),
                            ai=json.dumps((out.get("ai_prescore") or {}).get("prescore") or {}))
        # three fields with the most cells, with the current cell categories drawn on
        from app.cells import overlay_cells

        best = sorted(range(len(captured)), key=lambda i: -len(captured[i][1]["cells"]))[:3]
        for j, i in enumerate(best):
            rgb, res = captured[i]
            Image.fromarray(np.concatenate([rgb, overlay_cells(rgb, res)], 1)).resize((1024, 512)).save(
                OUT / f"{path.stem}_field{j}.jpg", quality=85)
        print(f"{name}: {len(sectors)} cells from {len(captured)} fields; current rule -> "
              f"{out['cell_evidence'].get('field_category') or out['cell_evidence'].get('measured_category')} "
              f"{out['cell_evidence'].get('percent')}", flush=True)


def categorise(sectors: np.ndarray, faint: float, strong: float, complete: float, anyf: float) -> np.ndarray:
    """Vectorised app.cells.classify_cell: 0..3 per cell."""
    valid = ~np.isnan(sectors)
    stained = valid & (sectors >= faint)
    nvalid = np.maximum(valid.sum(1), 1)
    completeness = stained.sum(1) / nvalid
    s = np.where(stained, sectors, np.nan)
    with np.errstate(all="ignore"):
        inten = np.nanmedian(s, axis=1)
    inten = np.where(np.isnan(inten), 0.0, inten)
    moderate = (faint + strong) / 2
    cat = np.zeros(len(sectors), dtype=np.int8)
    weakish = (inten >= faint) & (inten < strong)
    cat[(completeness >= anyf) & (inten >= faint) & (inten < moderate)] = 1
    cat[(completeness >= anyf) & (inten >= moderate)] = 2  # incomplete moderate/strong (atypical) -> 2+
    cat[(completeness >= complete) & weakish] = 2
    cat[(completeness >= complete) & (inten >= strong)] = 3
    return cat


def slide_call(cat: np.ndarray, rule: float = 10.0) -> int:
    pct = [100 * (cat == k).mean() for k in range(4)]
    if pct[3] > rule:
        return 3
    if pct[2] + pct[3] > rule:
        return 2
    if pct[1] + pct[2] + pct[3] > rule:
        return 1
    return 0


def analyse() -> None:
    data = {n: np.load(OUT / f"{Path(n).stem}.npz") for n in SLIDES}
    cur = dict(faint=0.25, strong=0.8, complete=0.5, anyf=0.1)
    print("\n== current cut points", cur)
    for n, d in data.items():
        cat = categorise(d["sectors"], **cur)
        pct = [round(100 * (cat == k).mean(), 1) for k in range(4)]
        mx = np.nanmax(d["sectors"], 1)
        print(f"{n}: truth {['0','1+','2+','3+'][SLIDES[n]]}, cells {len(cat)}, % cells 0/1+/2+/3+ {pct} -> "
              f"{['0','1+','2+','3+'][slide_call(cat)]} | membrane max-OD median {np.nanmedian(mx):.3f}, "
              f"p75 {np.nanpercentile(mx,75):.3f}, p90 {np.nanpercentile(mx,90):.3f}; cytoplasm OD median {np.median(d['cyto']):.3f}")
    print("\n== membrane DAB percentiles of each cell's strongest sector (what separates the slides?)")
    for n, d in data.items():
        mx = np.nanmax(d["sectors"], 1)
        print(n, [round(float(np.nanpercentile(mx, q)), 3) for q in (10, 25, 50, 75, 90, 95)])
    # grid search: which single cut-point sets sort all four slides correctly?
    hits = []
    for faint in np.arange(0.06, 0.40, 0.02):
        for strong in np.arange(0.30, 1.21, 0.05):
            if strong <= faint * 1.5:
                continue
            for complete in (0.3, 0.4, 0.5, 0.6, 0.75):
                for anyf in (0.05, 0.1, 0.15, 0.2):
                    calls = {n: slide_call(categorise(d["sectors"], faint, strong, complete, anyf)) for n, d in data.items()}
                    score = sum(calls[n] == SLIDES[n] for n in SLIDES)
                    hits.append((score, round(float(faint), 2), round(float(strong), 2), complete, anyf, calls))
    hits.sort(key=lambda h: -h[0])
    best = hits[0][0]
    print(f"\n== grid search over {len(hits)} cut-point sets: best = {best}/4 slides correct; "
          f"{sum(h[0] == best for h in hits)} sets reach it")
    for h in [h for h in hits if h[0] == best][:12]:
        print(f"  faint {h[1]}, strong {h[2]}, complete {h[3]}, any {h[4]} -> " +
              ", ".join(f"{k.split('_')[1][:3]}:{['0','1+','2+','3+'][v]}" for k, v in h[5].items()))
    (OUT / "grid_search.json").write_text(json.dumps([h[:5] + ({k: int(v) for k, v in h[5].items()},) for h in hits[:200]]))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--regions", default="artifacts/her2match_test_regions.json")
    p.add_argument("--analyse-only", action="store_true")
    a = p.parse_args()
    if not a.analyse_only:
        collect(a.regions)
    analyse()
