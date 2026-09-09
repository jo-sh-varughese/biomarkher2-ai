# Task brief — Model Quality: closing the moderate (2+) gap

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
`score`, `her2_score`, `verdict`, or `diagnosis`. Don't add one. Full context:
`PROJECT_PLAN.md` at the repo root (read this first) and
`IMPLEMENTATION_NOTES.md` for depth.

There are no real pathologist annotations for this project yet — the model
trains on **pseudo-labels** (a classical DAB-optical-density threshold rule,
`preprocessing/baseline.py`, cached to disk). A model agreeing with its own
training target proves nothing on its own; that classical rule must stay in
the comparison as a control, not be discarded once a deep model exists.

## Your mission

The segmentation model (ResNet18 encoder / U-Net decoder,
`models/unet_seg.py`) predicts 5 classes: background, negative, weak (1+),
moderate (2+), strong (3+). At full scale it scores:

| class | IoU |
|---|---|
| background | 0.861 |
| negative | 0.839 |
| weak (1+) | 0.666 |
| **moderate (2+)** | **0.589** |
| strong (3+) | 0.891 |

**Moderate (2+) is the weakest class by a real margin, and it's the exact
category that decides whether a patient gets sent for confirmatory FISH
testing.** Your job is to try the two cheapest, already-scaffolded levers on
this, run them honestly, and write up what actually happened — including if
the answer is "it didn't help." See `PHASE2.md`'s "Recommended next step" and
`PHASE5.md`'s "What would make this a stronger research contribution" for the
reasoning this is based on.

**Read before starting:** `PHASE2.md` (the original diagnosis of why
moderate fails), `PHASE5.md` (the U-Net comparison and current numbers),
`IMPLEMENTATION_NOTES.md`'s "Phase 2" section.

## Task 1 — Inverse-frequency class weights, run for real, on U-Net

The loss (`training/losses.py`) supports a literal `class_weights: "auto"` in
its config, resolved by `training/train.py:resolve_class_weights()` into an
actual inverse-frequency weight list computed over every fit tile (not a
sample) and written back into `resolved_config.yaml` so the run is
reproducible from its own output. **This exists and is tested
(`tests/test_losses.py`, `tests/test_train_loop.py`) but has never been run
to completion on the U-Net architecture** — it was only ever tried, and left
incomplete, on the now-removed SegFormer model.

What to do:
1. Copy `configs/training.yaml` to `configs/training_unet_weighted.yaml`.
   Change only `loss.class_weights: null` → `loss.class_weights: auto` and
   `output_dir: artifacts/phase2_unet` → `output_dir: artifacts/phase2_unet_weighted`.
   Nothing else changes — the comparison has to be controlled.
2. Run it: `python scripts/train_phase2.py --config configs/training_unet_weighted.yaml`
   (same 200 fit / 30 val patches, 4 epochs as the current baseline — expect
   a similar multi-hour CPU run to what produced the 0.589 number above;
   `scripts/train_phase2.py --resume` exists if it gets interrupted, see
   `PHASE5.md`'s "Resuming an interrupted run").
3. Compare per-class IoU against `artifacts/phase2_unet`'s current numbers
   (`training/metrics.py`'s confusion matrix output, or
   `scripts/plot_training.py --run artifacts/phase2_unet_weighted`).
4. Write up what happened in a new `PHASE5_CLASS_WEIGHTS.md`: the exact
   before/after per-class table, and an honest read of it — moving off zero
   like the old SegFormer experiment's epoch-1 result (see
   `IMPLEMENTATION_NOTES.md`) is a real answer either way; so is "moderate
   didn't move and other classes got worse," if that's what happens. State
   the decision rule *before* you look at the result, the way
   `configs/training_weighted.yaml`'s history in this project always did.

## Task 2 — Threshold sensitivity: is 2+ a hyperparameter problem?

`preprocessing/baseline.py`'s classical thresholder — the same one the model
is trained to imitate — cuts DAB optical density into classes at fixed
points, currently in `configs/preprocessing.yaml`:
```
dab_od_weak: 0.25
dab_od_moderate: 0.50
dab_od_strong: 0.80
```
`PHASE2.md` calls these "provisional Phase 1 numbers" and flags that if
moderate is a thin transitional band *by construction*, the cut points — not
the model — might be what needs adjusting. Nobody has tested that.

What to do:
1. Pick 2–3 alternative values for `dab_od_moderate` (e.g. try widening the
   moderate band: `0.42` and `0.58` instead of `0.50`/`0.80`) — a sweep, not
   a single guess.
2. For each, rebuild the pseudo-label cache
   (`python scripts/build_pseudo_labels.py --limit 900 --preview 8`, pointed
   at a new `cache_root` per variant so you don't clobber the existing one)
   and report the resulting class pixel-share (mirror `PHASE2.md`'s "Training
   target pixel balance" table) *before* training anything — this alone tells
   you whether moderate's 3.6% pixel share is an artifact of the cut points.
3. If a variant meaningfully changes moderate's pixel share without
   collapsing the others, train one comparison run on it (same protocol as
   Task 1) and report the result. If none do, that's the finding — write it
   up in the same `PHASE5_CLASS_WEIGHTS.md` (or split into
   `PHASE5_THRESHOLDS.md` if it gets long) rather than silently dropping it.
4. **This is ultimately a pathologist's call, not a hyperparameter search you
   resolve alone** (`PHASE2.md` says so explicitly) — frame your write-up as
   "here's what the data says, here's the open question for a pathologist,"
   not as a final answer.

## Task 3 (stretch, only if 1 and 2 are done) — per-cell membrane completeness

CAP/ASCO actually scores HER2 by membrane *completeness* around each cell,
not by area-intensity alone — this project currently approximates CAP with
an area-percentage measurement (see `PHASE2.md`'s "standing concerns").
Prototype (as an **offline, evaluation-only script**, like
`evaluation/cap_mapping.py` — never wired into `app/`, per the "no score in
the live app" rule) a classical connected-components measure over the DAB
mask: for each stained blob, is the membrane ring complete or broken? Compare
that signal against the model's current moderate-class errors. This is
exploratory — a clear negative result, honestly reported, is a legitimate
outcome.

## Acceptance / how to know you're done

- `pytest -q` still shows all existing tests passing, plus new tests for
  anything you add (a new evaluation script needs a test the way
  `evaluation/stain_variation.py` has `tests/test_stain_variation.py`).
- A write-up doc exists with real numbers, not projected ones, in the same
  "measured, not assumed" voice as `PHASE2.md`/`PHASE5.md` — say what you
  tried, what happened, and what you'd try next if you had more time.
- You have not touched `app/`, `evaluation/`'s conformal/CAP-mapping code, or
  anyone else's files (see `CONTRIBUTING.md`).
- **You have not built anything related to virtual staining** — out of scope
  for this round.

## Files you'll work in

`training/`, `models/`, `configs/` (new config files), `preprocessing/`
(reading, and possibly a new script that calls it — don't change
`preprocessing/baseline.py`'s defaults without discussing it, other things
depend on them), plus whichever `PHASE5_*.md` you create. See
`CONTRIBUTING.md` for the branch/PR workflow — suggested branch name:
`yourname/moderate-class-experiments`.
