# Task brief — Application & Product: viewer polish and whole-slide groundwork

**Give this whole file to your LLM (ChatGPT, Gemini, Claude, whatever you're
using) as context before you start.** It's written to be self-contained —
paste it in, tell your LLM "help me do this in the repo at [path/URL]", and
it should have what it needs.

## What this project is (one paragraph)

BioMarkHER2 is an AI-assisted tool that measures HER2 IHC staining intensity
in breast-cancer biopsy images, to help pathologists score slides 0/1+/2+/3+
more consistently. **It is a pre-scoring assistant a pathologist reviews and
confirms — never an autonomous scorer.** That rule is enforced by actual
tests (`tests/test_app.py`): no code anywhere may produce a field named
`score`, `her2_score`, `verdict`, or `diagnosis`. **This rule applies to
everything you build here too** — a batch report tool is just as bound by it
as the live viewer. Full context: `PROJECT_PLAN.md` at the repo root (read
this first) and `app/README.md` for how the current viewer works.

## Your mission

The review-viewer (`app/`) is a complete, tested, local web app — pick or
upload a patch, see the model's prediction next to the classical baseline,
record a review, export a PDF. Two things are missing that don't require any
new model or real data: (1) groundwork for eventually handling whole slides
instead of single patches, and (2) a way to demo the tool's output across
*many* patches at once, and user-facing documentation.

**Read before starting:** `app/README.md`, `IMPLEMENTATION_NOTES.md`'s "The
review-viewer frontend" section, and `PROJECT_PLAN.md`'s §5b (this task
covers the "whole-slide stitching" and "batch/summary report" items listed
there).

## Task 1 — Prove the tiling/stitching logic at larger-than-patch scale

`app/analysis.py`'s `Analyzer.predict()` already tiles an image of *any*
size into the model's native tile size, edge-replicate-pads ragged edges, and
stitches predictions back — this was built so Phase 3/6 (real whole-slide
images, whenever they arrive) wouldn't need new stitching logic, just a
bigger input. **This has never been exercised at a scale bigger than a single
1024×1024 patch.** Your job is to prove it works — and find out how slow it
is — before real whole-slide data shows up and makes that an emergency.

What to do:
1. Write a small script (`scripts/build_mock_slide.py` or similar) that
   stitches an N×N grid (start with 4×4, i.e. 16 patches) of real patches
   from `data/raw` into one large synthetic "mock slide" image — a real
   image, not a placeholder, so tissue detection and the model see real
   pixels at every tile boundary.
2. Run `Analyzer.predict()` (or `.analyze()`) on the mock slide. Confirm:
   the output covers the whole image with no gaps or seams at tile
   boundaries, the per-tile coordinate bookkeeping is correct (compare a
   known patch's prediction against running that same patch alone), and
   record wall-clock time so there's a real number for "how long would a
   patch this many tiles wide take."
3. Add a test (`tests/test_analysis_large_image.py` or extend the existing
   analysis tests) that builds a small synthetic mosaic (doesn't need to be
   4×4 — 2×2 is enough for a fast test) and asserts stitching correctness,
   the same way `app/analysis.py`'s existing tests check the single-patch
   case.
4. Write up what you found (timing, any seam/edge artifacts, memory) in a
   short new `PHASE6_NOTES.md` — this is explicitly *not* claiming Phase 6
   (real whole-slide stitching) is done; it's the groundwork that makes it
   fast to finish once real WSI data exists. Say that explicitly.

## Task 2 — Batch/summary report mode

Right now the viewer analyzes one patch at a time, reviewed by one person.
For demoing to the Kottayam stakeholder (or anyone else) without a live
pathologist clicking through images one at a time, build a CLI script
(`scripts/batch_report.py`) that:

1. Takes a directory of patches (e.g. one class folder from `data/raw`) or a
   list of patch IDs.
2. Runs `Analyzer.analyze()` on each (reuse the existing analysis engine —
   don't reimplement tiling/tissue-detection/model-inference).
3. Emits one summary artifact — a CSV with one row per patch (area
   percentages per class, tissue fraction, agreement/disagreement with the
   classical baseline) plus, if you have time, an HTML page with the same
   four-panel layout the live viewer uses, one section per patch.
4. **Applies the same "never a score" rule** — the output reports
   *measurements* (area percentages), never a HER2 score/verdict. Add a test
   for this the way `tests/test_app.py` tests the live API — scan the
   script's output for the same forbidden field names.

## Task 3 — User-facing documentation and accessibility pass

1. Write a short, plain-language "how to use this tool" page aimed at a
   pathologist who has never seen it before — no jargon, a few screenshots
   if you can capture them, pointing out the four panels and what "cannot
   assess from this field" is for. This is different from `app/README.md`
   (which is developer-facing) — put it somewhere clearly separate, e.g.
   `app/USER_GUIDE.md`.
2. Check the exported PDF report (`app/report.py`, `POST /api/report`) prints
   legibly in black-and-white (the app's colour palette is already
   colour-blind-safe and monotonically darker with intensity — confirm the
   PDF preserves that, since a report is far more likely to be printed than
   the live page is).
3. Confirm the moderate (2+) warning row is still clearly visible in the PDF
   export, not just the live page (`IMPLEMENTATION_NOTES.md` explains why
   this specific row is flagged inline rather than only in a footnote — the
   same reasoning applies to a printed report, maybe more so).

## Acceptance / how to know you're done

- `pytest -q` still passes in full, plus new tests for whatever you add.
- Task 1's write-up and test exist even if the honest finding is "this is
  slow" or "there's a subtle edge artifact" — that's useful information,
  not a failure to hide.
- Task 2's batch tool has a test proving it never emits a forbidden field.
- **You have not built anything related to virtual staining** — out of scope
  for this round.

## Files you'll work in

`app/` (mostly `app/analysis.py` reads, new scripts, new tests — avoid
changing `app/server.py`'s routes or `app/static/` unless your task requires
it, to minimize overlap with anyone else touching the live viewer), new
`scripts/build_mock_slide.py` and `scripts/batch_report.py`, new
`PHASE6_NOTES.md` and `app/USER_GUIDE.md`. See `CONTRIBUTING.md` for the
branch/PR workflow — suggested branch name: `yourname/viewer-and-mockslide`.
