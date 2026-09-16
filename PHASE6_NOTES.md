# Phase 6 Notes — Viewer, Mock Slide and Batch Analysis

Covers `tasks/person3_app_product.md`'s three tasks: proving the existing
tiling/stitching logic at larger-than-patch scale, a batch/summary report
mode, and user-facing documentation. As that task doc is explicit about:
**this is groundwork, not a claim that Phase 6 (real whole-slide stitching)
is done** — no real whole-slide image exists yet (see `PROJECT_PLAN.md` §2),
so everything below is validated against synthetic mosaics of the approved
public patch dataset.

## 1. Mock slide generation (`scripts/build_mock_slide.py`)

A synthetic mock slide is built by stitching real HER2 IHC patches from
`data/raw/train` into one large image.

Configuration (defaults):

- Grid: 4 × 4 (16 patches)
- Patch size: 1024 × 1024 px
- Mock slide size: 4096 × 4096 px
- Patches are round-robined across all four class folders
  (`class_0`/`class_1+`/`class_2+`/`class_3+`) rather than taken in sorted
  order — sorted order alone puts every tile in `class_0`, since that folder
  has more than 16 files and sorts first, which was tried and produced a
  mosaic with no staining variety at any tile boundary at all.

Artifacts:

- `artifacts/mock_slide_4x4.png`
- `artifacts/mock_slide_4x4.csv` (manifest: source patch, grid row/col,
  pixel coordinates)

## 2. Running `Analyzer.predict()` on the mock slide, with real numbers

`scripts/build_mock_slide.py --analyze <run_dir>` runs the trained
checkpoint's `Analyzer.predict()` over the *entire* stitched mock slide (not
just a small synthetic case) and checks two things:

1. **Coverage** — the stitched prediction map covers the full 4096×4096
   image with no gap (checked by shape).
2. **Per-tile coordinate correctness** — one tile is read back out of the
   stitched prediction at its recorded (x, y) offset, and the same source
   patch is analyzed completely on its own; the two must match exactly. A
   transposed row/col or an off-by-one in the tiling loop would make these
   disagree even though the stitched image still looks plausible.

Real run against `artifacts/phase2_unet` (the trained checkpoint from
Phase 5, CPU-only machine, in_channels=4, model tile size 512×512, so the
4096×4096 slide is 64 model tiles):

```
Analyzer.predict() on the mock slide took 40.60s (4096x4096 px, 512px model tiles).
Coordinate check (tile read out of stitched slide vs. same tile analyzed alone): MATCH
```

Result recorded at `artifacts/mock_slide_4x4_analysis.json`. 40.6s for 64
tiles is ≈0.63s/tile on this CPU-only machine — the number to extrapolate
from for a real whole-slide image once one exists (a WSI with, say, several
thousand tiles at this tile size would be tens of minutes on this hardware;
this is exactly the kind of number Task 1 asked to have on record before
that becomes a surprise).

**This does not claim there are no artifacts at all** — only that shape
coverage and per-tile coordinate bookkeeping are both correct on this mosaic.
It does not test cross-tile smoothing/blending (there is none — tiles are
independent, non-overlapping predictions by design, see `app/analysis.py`'s
`_predict_tiles` docstring), and it does not test a real scanner's stitching
artifacts (out of scope until real WSIs exist).

## 3. Large-image test coverage (`tests/test_analysis_large_image.py`)

Two tests, testing two different kinds of thing:

- `test_analysis_large_image_covers_all_tiles` — a 2×2 synthetic image is
  fully covered, correct shape/dtype, every class value in range.
- `test_analysis_large_image_tile_coordinates_are_correct` — the same
  per-tile coordinate check described in §2, but as a fast, deterministic
  unit test using `tests/synthetic.py`'s `positioned_grid` (each tile
  carries content unique to its own grid position, so a coordinate mixup
  shows up as a mismatch rather than a plausible-looking image) and an
  untrained model, so it runs in seconds and needs no trained checkpoint.

```
2 passed
```

## 4. Batch/summary report (`scripts/batch_report.py`)

Runs the existing `Analyzer.analyze()` over a directory of patches (or an
explicit `--patch-ids` list) and writes one CSV row per patch: tissue
percentage, model and baseline area percentages per class, and
`disagreement_percent` (the fraction of tissue pixels where the model and
classical baseline land on different classes). Reuses the analysis engine
end to end — no tiling/tissue-detection/model-inference is reimplemented.

**Bug found and fixed:** the first version of this script populated an
`agreement` column with `result.get("agreement")` — but
`PatchAnalysis.to_dict()` (`app/analysis.py`) never produces a key called
`"agreement"`, only `"disagreement_percent"`. `.get()` on a missing key
returns `None` silently, so that column was blank on every row it ever
wrote, for every image, always — not just for the one sample image it
happened to be checked against. The original `artifacts/batch_report.csv`
in this repo's history shows the blank cell; it was misread at the time as
something specific to that one image rather than a hard bug. Fixed by
reading the field that actually exists.

`tests/test_batch_report.py` was rewritten to catch exactly this class of
bug: it runs the real script functions
(`run_batch_report`/`write_report`) against a real (untrained, fast)
`Analyzer` and a real CSV, and asserts `disagreement_percent` is present and
numeric on every row — not just that the script's *source text* avoids
certain literal strings, which is what the original test did and which
cannot catch a wrong-key bug like this one.

```
6 passed
```

Verified against the real trained checkpoint on real data
(`data/raw/test/class_2+`, 4 patches, `artifacts/batch_report_sample.csv`):

```
patch_id,tissue_percent,...,disagreement_percent
her2-1+-score_test_100.png,48.42,...,9.46
her2-1+-score_test_16.png,68.27,...,17.11
her2-1+-score_test_18.png,56.57,...,20.57
her2-1+-score_test_431.png,56.83,...,11.57
```

A full-folder run over all of `data/raw/test/class_2+` (226 patches) was
also completed against the real checkpoint, end to end, with no crash:

```
Batch report created: artifacts\batch_report.csv
Images analyzed: 226
```

All 226 rows have a real, non-blank `disagreement_percent` (checked
directly against the CSV, not just re-reading the script), and no row
carries a forbidden field. This run comfortably exceeded 10 minutes
end-to-end (long enough that it had to run as a background job rather than
inline) -- per-patch cost includes the full pipeline (tissue detection, DAB
baseline, model inference), not just `predict()`, so it's slower than the
mock-slide number in §2. This confirms the same finding as the original
Phase 6 pass: a full-folder batch is slow enough on this CPU-only machine
that demoing it works best against a handful of representative patches, not
an entire class folder, until this runs somewhere with a GPU.

## 5. User guide (`app/USER_GUIDE.md`)

A pathologist-facing (not developer-facing) guide, separate from
`app/README.md`: what the four panels mean, how to read the percentages,
the moderate (2+) limitation, why a pathologist review step is required, and
what the exported PDF contains.

## 6. PDF report legibility (Task 3, items 2–3)

Checked by generating a real report from the trained checkpoint against a
patch with real moderate (2+) content
(`data/raw/test/class_2+/her2-1+-score_test_16.png`, 6.62% model-predicted
moderate area) via `app.report.build_report_pdf`, then reading the rendered
PDF:

- **The area-percentage table** (`app/report.py`'s `_render`) is plain
  black text on white, one row per class including moderate (2+) — no
  colour-only encoding, so it survives black-and-white printing exactly as
  well as any other row.
- **The moderate (2+) limitation notice** (`MODEL_LIMITATION` in
  `app/analysis.py`) is included in `caveats` unconditionally on every
  report — not a colour flag, not something that only appears if a
  threshold is crossed — so it prints as an ordinary paragraph on every
  single report, regardless of what page or panel a reader is looking at.
- **The four image panels** (original/tissue/model/baseline) are the exact
  same PNG bytes the live viewer renders — `_data_uri_to_image` decodes the
  data URI as-is rather than re-rendering, so the same colour-blind-safe,
  monotonically-darker-with-intensity palette (`INTENSITY_COLORS`,
  `app/analysis.py`) is what ends up on paper.

No code changes were needed in `app/report.py` — the legibility properties
Task 3 asked to confirm already held; this section is the confirmation, not
a fix. `app/USER_GUIDE.md` now has a short "Printing the report" note
saying so.

## 7. Full test suite

```
291 passed
```

(283 tests as of `PROJECT_PLAN.md`'s count, plus this phase's 8: 2 in
`tests/test_analysis_large_image.py`, 6 in `tests/test_batch_report.py`.)

## 8. Limitations

- No real whole-slide image has been stitched or analyzed — everything here
  is a synthetic mosaic of the public patch dataset, exactly as
  `tasks/person3_app_product.md` scoped it.
- The coordinate-correctness check compares one tile per run; it does not
  exhaustively check all 16 (mock slide) or 4 (unit test) tiles, though the
  tiling loop treats every tile identically, so there is no structural
  reason to expect the others to differ.
- Batch-report throughput on this CPU-only machine is not fast enough for
  an interactive full-folder demo; a GPU machine or a smaller representative
  sample is the practical path until that changes.
- **Virtual staining was not touched** — out of scope for this round, per
  `tasks/person3_app_product.md`.
