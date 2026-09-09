# BioMarkHER2 — Project Plan

**Start here.** This is the onboarding document: what this project is, why it's
built the way it is, exactly how much of the original brief is covered today,
and what's genuinely left to do. For line-by-line technical depth on any one
phase, this document points you to `IMPLEMENTATION_NOTES.md` and
`PHASE2.md` / `PHASE4.md` / `PHASE5.md` — read this first, those second.

---

## 1. What this project is

BioMarkHER2 is a final-year academic project (Kottayam Medical College is the
clinical reference point) proposing an **AI-assisted measurement tool** for
HER2 immunohistochemistry (IHC) slides in breast cancer diagnosis.

Pathologists score HER2 IHC on a 0 / 1+ / 2+ / 3+ scale from membrane
staining intensity and completeness. That score decides treatment: 3+ is
positive (targeted therapy), 0/1+ is negative-to-low, and **2+ ("equivocal")
triggers a second, expensive confirmatory test (FISH/ISH)**. Manual scoring —
especially the 0-vs-1+ and 2+-vs-3+ boundaries — is subjective and varies
between observers. The project's brief (see the original proposal deck,
`BioMarkHER2 AI_ - Copy (1).pdf`) is to reduce that variability with an
AI-assisted, *quantitative* pre-scoring step — not to replace the
pathologist's judgement.

**The one rule everything else follows:**

> This is a pre-scoring assistive tool that a pathologist reviews and
> confirms — never an autonomous final-scorer.

That's not a mission statement sitting in a slide deck — it's enforced as
actual, tested code: no API response or UI anywhere is allowed to carry a
field named `score`, `her2_score`, `verdict`, or `diagnosis`
(`tests/test_app.py` scans for this on every run), and a review can only be
recorded by an explicit human submit action. Whoever picks up a task below:
**do not build a code path that emits a HER2 score, ever.** Full rationale in
`IMPLEMENTATION_NOTES.md`'s "The one rule everything else follows".

## 2. The data reality that shapes every decision

Two facts explain almost every engineering choice in this codebase, and
they're not obvious from reading the code alone:

- **No real whole-slide images exist yet.** The 84 Kottayam slides this
  project is ultimately for are not digitized — no scanner output anywhere.
  Everything built so far is validated against an approved public stand-in
  dataset, **HER2_IHC_40X**: ~11,000 pre-cut 1024×1024 RGB patches, one HER2
  score per patch (its folder) and one per source slide (its filename
  prefix) — no pixel-level annotations, no slide IDs. This is classification
  data standing in for a segmentation task.
- **The development machine is CPU-only.** No GPU, no `nvidia-smi`. Every
  model, batch size, and epoch count in this repo is sized to actually finish
  on a laptop CPU; "train on everything" is measured in days here, not hours.

Consequences worth internalizing before touching anything:

- There are no pixel masks to train on — the segmentation targets are
  **pseudo-labels**: the output of a classical DAB-threshold rule, cached to
  disk so they can be inspected, not trusted blindly. A model that agrees
  with its own training target proves nothing on its own — that's why the
  classical thresholder is carried through as an experimental control at
  every evaluation stage, not thrown away once the deep model exists.
- There's no way to do a true slide-level train/validation split (no slide
  IDs). The best available substitute — grouping by the dataset's own
  filename-origin token — is used, and is labelled `leakage_free=False`
  everywhere it appears. Nobody should quote a validation number from this
  project without that caveat attached.

## 3. What's been built (the approach, phase by phase)

| Phase | What it does | Status |
|---|---|---|
| **Phase 1** — `preprocessing/` | Stain deconvolution (Ruifrok & Johnston), tissue detection by optical density, a classical DAB-threshold intensity classifier, tiling. This is also the pseudo-label generator Phase 2 trains on, and the thing the frontend calls live on every upload. | **Done**, measured at every stage that could silently go wrong (see `IMPLEMENTATION_NOTES.md`). |
| **Phase 2** — `training/`, `models/` | Dataset construction from patch labels, a leakage-aware (if not leakage-*free*) split, the segmentation model, the training loop. Two full architecture attempts were run and compared (see Phase 5). | **Done and runnable.** Moderate (2+) is the one class still weak — see §5. |
| **Phase 4** — `evaluation/` | Conformal prediction (with a stain-shift-weighted extension for cross-institution uncertainty), stain-variation analysis across the dataset's provenance groups, offline ASCO/CAP 2018 score mapping + expert-agreement statistics (Cohen's kappa), PDF report export, Docker packaging. | **Software complete.** Two of its four objectives are only run at smoke scale or have zero real data to evaluate yet — see §5. |
| **Phase 5** — `models/unet_seg.py` | A second architecture (ResNet18 encoder / U-Net decoder, fed RGB **+ DAB optical density** as a 4th channel) was built and compared head-to-head against the original SegFormer model, same data/split/seed/epochs. | **Done. Decision made:** U-Net won on every class — most dramatically on moderate (2+), IoU 0.589 vs SegFormer's 0.00006. SegFormer has been removed from the codebase entirely, not kept as an option. |
| **The review-viewer app** — `app/` | A local, dependency-free (standard library only) web app: pick or upload a patch, see the model's prediction next to the classical baseline (always side by side, never one without the other), record a pathologist's confirmed score, export a PDF report. | **Done and demonstrable.** No auth, no TLS — a local demo/review aid, not a deployable clinical service, by design. |

**283 tests pass** (`pytest -q`), spanning every phase above. The tests
aren't just correctness checks — a real category of them (`tests/test_app.py`
especially) encode the framing rules in §1 as literal assertions, specifically
because those are the properties a well-intentioned future edit could erode
without anyone noticing.

## 4. Coverage against the original project brief

The original proposal (`BioMarkHER2 AI_ - Copy (1).pdf`) lists 9 scope items.
Here's the honest state of each:

| # | Scope item (as proposed) | Status |
|---|---|---|
| 1 | Digital processing of IHC slides into WSI | **Blocked on data** — no scanner, no real slides exist to digitize yet. Not a code gap. |
| 2 | Tissue detection to exclude background | **Done** — `preprocessing/tissue.py` |
| 3 | Stain normalization + colour deconvolution to isolate DAB intensity | **Done** — `preprocessing/stains.py` (normalization implemented, off by default: the substitute dataset is single-source, so there's nothing to correct yet) |
| 4 | Patch extraction and patch-level analysis | **Done** — `preprocessing/tiling.py`, and `app/analysis.py` tiles/stitches images of any size |
| 5 | AI/ML model for intensity classification (weak / moderate / strong) | **Done, one class still weak.** Weak (1+) and strong (3+) are solid (IoU 0.67–0.89); moderate (2+) — the class that decides reflex FISH testing — sits at 0.589. See §5. |
| 6 | Total tissue area + area % per intensity category | **Done** — reused everywhere (`preprocessing/baseline.py:area_distribution`, the app's table, PDF reports) |
| 7 | Heatmaps + slide-level quantitative summary reports | **Partial.** Patch-level intensity maps and PDF reports are done. True *slide*-level heatmaps need real WSIs to stitch across — see §5's Phase 6. |
| 8 | Validation against pathologist annotations (accuracy, kappa) | **Built, tested, zero real data yet.** `evaluation/cap_mapping.py` computes exact/within-one-category agreement and quadratic-weighted Cohen's kappa against `artifacts/reviews.jsonl` — which has zero real entries because no pathologist has used the viewer yet. This is blocked on a person, not on code. |
| 9 | Integration into a digital pathology workflow as a pre-scoring tool | **Done** — the review-viewer app, with the "assistive, not autonomous" framing enforced by tests, not just prose. |

**Bottom line:** 6 of 9 scope items are done; 1 is genuinely partial
(slide-level heatmaps); 2 are blocked on data no engineering effort in this
repo can substitute for (real WSIs, real pathologist reviews) — they are
*ready to activate the moment that data exists*, not unstarted.

## 5. What's actually left to do

Split deliberately into two buckets, because they need completely different
kinds of effort.

### 5a. Blocked on data — nobody can code their way past these

- **The Kottayam slides.** Still not digitized. Every result in this project
  is validated against the public substitute dataset until real slides
  arrive.
- **Real pathologist reviews.** `scripts/evaluate_cap_agreement.py` is
  complete and tested against synthetic data; it activates automatically the
  first time a real reviewer confirms a score in the viewer. Nobody should
  spend engineering time here — it can only be *ready*.

### 5b. Buildable now — this is the pool the team divides

- **Moderate (2+) is still the model's weakest class** (IoU 0.589 vs
  0.67–0.89 for the others), and it's the exact category that decides reflex
  FISH testing. Untried levers: inverse-frequency class loss weighting with
  the new U-Net (the code supports it, no run has been done), and a
  sensitivity check on the classical threshold cut-points that define the
  class in the first place.
- **Phase 4's conformal calibration has only been run at smoke scale**
  (40 patches) — a full run over the ~1,900-patch reserved holdout is
  software-ready but unrun (multi-hour CPU job).
- **Docker packaging is written but never verified** — no Docker on the
  original dev machine.
- **No CI** — tests only run when someone remembers to run them locally.
- **Whole-slide stitching (the project's own "Phase 6") hasn't been started
  at the codebase level**, but a real chunk of it — tiling and stitching
  predictions across an image far larger than one patch — can be built and
  tested *now*, against synthetic mosaics of the existing dataset, without
  waiting for a real WSI.
- **The review-viewer** could use a batch/summary report mode (useful for
  demoing to the Kottayam stakeholder without a live pathologist per image)
  and a plain-language user guide.

These are exactly the items divided across three people in `tasks/` — see
§7. **Virtual staining is deliberately excluded from this split** (out of
scope for the current round of work).

## 6. How the pieces fit together (for anyone new)

```
preprocessing/    Phase 1 -- stain math, tissue detection, the classical baseline
                  (also the pseudo-label generator Phase 2 trains on)
training/         Phase 2 -- dataset, splits, losses, the training loop
models/           the ResNet18-UNet wrapper + architecture dispatch (models/__init__.py)
evaluation/       Phase 4 -- conformal prediction, stain variation, CAP/ASCO mapping
app/              the review-viewer frontend + PDF report export
configs/          YAML configs -- one file fully describes one run
scripts/          CLI entry points that call into the packages above
tests/            283 tests -- the project's actual specification, in executable form
artifacts/        everything a run produces (gitignored -- regenerable, not source)
data/             raw dataset + cached pseudo-label targets (gitignored)
```

Config discipline is the same everywhere: plain dataclasses + YAML (no
Hydra), and every config loader rejects an unknown key loudly rather than
silently ignoring a typo.

## 7. Where to go next

- **Contributing code?** Read `CONTRIBUTING.md` for the branch → PR workflow.
- **Picking up one of the three divided workstreams?** Each has a
  self-contained brief in `tasks/` (`person1_model_quality.md`,
  `person2_evaluation_infra.md`, `person3_app_product.md`) written so you —
  or an LLM you paste it into — has everything needed to start without
  reading the whole codebase first.
- **Need the technical detail behind any claim above?** `IMPLEMENTATION_NOTES.md`
  is the full account; `PHASE2.md`, `PHASE4.md`, `PHASE5.md` are the
  per-phase deep dives with real numbers.

## 8. Running it yourself

```
# set up
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate
pip install -r requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu   # see requirements.txt's own note

# confirm the baseline: this must pass before you start any task
pytest -q

# launch the review-viewer
python -m app.server --run artifacts/phase2_unet
# open http://127.0.0.1:8000
```

Repo: `https://github.com/jo-sh-varughese/biomarkher2-ai` (primary,
private — ask to be added as a collaborator) and
`https://gitlab.com/her2-final-year-group/biomarkher2-ai` (kept in sync).
