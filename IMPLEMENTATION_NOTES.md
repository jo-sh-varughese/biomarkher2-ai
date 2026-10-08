# BioMarkHER2 — Implementation Notes

A complete account of what has been built, why each piece exists, and how the
pieces fit together. Written so that someone who was not in the room for any
of the decisions — a teammate, an examiner, a future version of you six months
from now — can pick this up and understand not just *what* the code does but
*why* it does it that way.

**Last revised: 2026-10-06.** This file was brought in line with the repository
as of the 2026-10-03 "four objectives complete" commit, and then updated for the
2026-10-06 changes (8-epoch model adopted as the default, tumour segmenter removed,
on-slide control calibration, in-app prediction-set recalibration). Where it summarises a
subsystem, the detailed and most current numbers live in the document named in
that section (`PHASE4.md` "Final status", `PHASE5.md`, `docs/*.md`); if a number
here ever disagrees with those, they win.

If you only read one section, read [The one rule everything else follows](#the-one-rule-everything-else-follows)
and [Where the project actually stands](#where-the-project-actually-stands).

---

## What this is

BioMarkHER2 is an AI-assisted **HER2 immunohistochemistry (IHC) measurement and
pre-scoring system** built as a final-year academic project, with Government
Medical College Kottayam as the clinical reference point. Pathologists score
HER2 IHC on a 0 / 1+ / 2+ / 3+ scale (ASCO/CAP 2018, updated 2023) from the
completeness and intensity of membrane staining; the 2+ ("equivocal") category
triggers a second, more expensive in-situ hybridisation (ISH) test, and the
0 / ultralow / 1+ boundary now decides HER2-low eligibility.

For each analysed field or whole slide the system reports, side by side:

* a **measurement** — how much of the tissue area is stained at each intensity,
  from a segmentation model and, always next to it, from a classical
  DAB-threshold control;
* **cell-level ASCO/CAP evidence** — every detected cell classified by membrane
  completeness and intensity, with the 10 % rule applied;
* a **gated AI pre-score** (grade, probabilities, a 90 % conformal prediction
  set) that a pathologist must confirm, shown only at sites that have been
  validated;
* **ISH decision support** and explanations, and a **pathologist review record**.

It is an assistive tool, never an autonomous scorer.

### Data actually used

No local patient slides exist yet (no scanner; Kottayam slides are not
digitised). Everything has been built and validated on public data used as
approved stand-ins:

| Dataset | Role | Notes |
|---|---|---|
| **HER2_IHC_40X** (~11,000 pre-cut 1024×1024 patches, one score per patch) | Training site; pseudo-label source; in-domain holdout | single source, no slide IDs (see "The split problem") |
| **BCI** (Liu et al., CVPR-W 2022, Hamamatsu, ~20×) | A genuinely different second institution; cross-site evaluation and (in Run B) training | labels are case scores from the pathology report |
| **ACROBAT case 39** (HER2 IHC whole slide, Karolinska, CC BY 4.0, 10×) | The one real whole slide; tests the viewer, the exclusions and the safety rules | too coarse to be scored, correctly receives no pre-score |

The machine used for development is CPU-only; the larger v2 models were
trained on rented GPUs under a fixed budget (docs/V2_TRAINING_PLAN.md). That
CPU/GPU split shapes many engineering choices below.

## The one rule everything else follows

> Correctness, interpretability, and defensibility of every result matter
> more than speed of delivery. This is a **pre-scoring assistive tool** that a
> pathologist reviews and confirms — never an autonomous final-scorer.

Concretely, that rule has been enforced as actual code and actual tests, not
just as a sentence in a document:

- **There is no verdict or diagnosis field.** The only score-like output is the
  AI pre-score, which lives only under `ai_prescore`, always carries
  `requires_pathologist_confirmation: true`, and is never a final result.
  `tests/test_app.py` and `tests/test_prescoring.py` assert this by scanning
  the JSON the server returns.
- **The pre-score is gated (design changed 2026-10-02 at the project owner's
  request; it replaced the earlier "never emit a score" design).** It is shown
  only when the **site safety gate** (`evaluation/safety_gate.py`) has validated
  the site against a local validation record (defaults: ≥100 cases, ≥90 %
  accuracy, QWK ≥0.85, ≤1 % errors of two or more grades; thresholds for the
  pathologists to set), or in an explicit `--research-prescores` mode where every
  pre-score carries a red "research mode, never for patient care" warning. At
  any other site it is computed, withheld, and logged (`--shadow-log`) so the
  site can be validated later; with unknown magnification it is **blocked**.
  Why: at a hospital the model had never seen, its most confident answers were
  its worst (25.6 % correct in the top 20 % by confidence;
  docs/V2_TRAINING_PLAN.md). Full description: docs/PRESCORING_SYSTEM.md.
- **The viewer's raw measurements never impersonate a score.** The area-based
  "stained by intensity" table is labelled with words (negative / weak /
  moderate / strong) and folded under supporting measurements, so a tissue-area
  "1+" cannot sit beside an AI "3+" and be read as a grade.
- **A human-review step is mandatory and cannot fire automatically.** The score
  is **not pre-filled from the AI** (to avoid automation bias); a final record
  needs an attestation; disagreeing with the AI requires a reason (this is how
  the model is audited). "Cannot assess from this field" is a first-class
  option — forcing a choice would manufacture agreement nobody gave.
- **Every number that could be misread is labelled with what it is**, inline,
  not in a footnote: pseudo-labels vs. pathologist annotations, tissue-area
  percentage vs. CAP's tumour-cell percentage, and the model's weakest class.
- **Nothing is thrown away that would make a result hard to audit later.**
  Every training run writes its resolved config, its exact data split (with
  caveats), per-epoch metrics, a confusion matrix, and the checkpoint, all as
  plain files; every analysis records which model version produced it.

---

## Project layout

```
preprocessing/    Phase 1 — pixel-level image processing, stain math, the classical baseline
training/         Phase 2/v2 — datasets, splits, losses, training loops (CPU and GPU), site adaptation
models/           ResNet-UNet (unet_seg.py, RGB+DAB 4-channel input; ResNet18 shipped, ResNet-50
                  for v2) and the multi-task score head (multitask.py). SegFormer was
                  compared at full scale and removed (PHASE5.md).
evaluation/       Conformal prediction (incl. cross-site, stain-shift weighted), stain variation,
                  CAP/ASCO mapping and agreement, safety gate, site fingerprint, control calibration,
                  membrane completeness, streaming
app/              Backend (stdlib HTTP server), analysis, pre-score, cell evidence, ISH decision,
                  explanations, report (PDF), review record, authentication, learning loop
wsi/              Whole-slide reader, tissue, ink and control-core exclusion, field selection,
                  on-slide control calibration, slide report and routes (no tumour segmenter)
ui/               React review portal (built into the Docker image)
configs/          YAML configs — one file fully describes one run
scripts/          CLI entry points; scripts/pod/ for the GPU-pod workflow
docs/             Subsystem documents (see the documentation map in README.md)
tests/            ~40 test files; the project's specification in executable form
artifacts/        everything a run produces (not source — regenerable)
data/             raw datasets, cached pseudo-label targets, slides
```

Config discipline is the same everywhere: **plain dataclasses + YAML, no
Hydra**, and every config loader rejects unknown keys loudly
(`preprocessing/config.py:build_config`, mirrored in `training/config.py`).
A typo in a YAML key fails the run instead of silently being ignored — that
is deliberate, because a silently-ignored typo is exactly how a run becomes
irreproducible.

---

## Phase 1 — Preprocessing (`preprocessing/`)

Phase 1 turns a raw RGB IHC patch into a tissue mask, a classical intensity
classification, and area percentages. It is also the module every later
phase leans on: Phase 2 trains on Phase 1's classification (as pseudo-labels),
and the application calls Phase 1 live on every analysis.

### Stain deconvolution (`preprocessing/stains.py`)

HER2 IHC slides are dual-stained: haematoxylin (blue, counterstains nuclei)
and DAB (brown, marks the HER2 antibody — this is the actual signal). A raw
RGB pixel is a mixture of both, so the first job is to separate them.

This uses **Ruifrok & Johnston colour deconvolution** (2001): each stain has
a known absorbance direction in optical-density space, an image is converted
to OD (`OD = -log10(I / I0)`, which turns light absorption into something
additive), and a 3×3 stain matrix (haematoxylin, DAB, and a residual
direction from their cross product, so the matrix is invertible) is inverted
to recover per-stain concentration maps. The DAB channel from that
decomposition is the number the entire quantitative method rests on.

**Adaptive stain-vector estimation is Macenko's method** (SVD of the OD
distribution, `estimate_macenko_stain_matrix`) — *not* non-negative matrix
factorisation. Two bugs in that estimator were found and fixed on 2026-10-01
(eigenvector sign, and H/DAB row order); every earlier stain-variation number
was computed with the buggy version and is superseded (PHASE4.md).

Stain **normalization** (Macenko or Reinhard, `apply_normalization`) is
implemented but **defaults to off** for single-site work, because normalising
silently shifts the exact DAB optical densities the thresholds below are
defined on. Cross-site use is different: see "Cross-institution stain shift".

### Tissue detection (`preprocessing/tissue.py`)

This mask becomes the **denominator of every percentage the tool ever
reports**, so its correctness matters more than its sophistication.

The first implementation used Otsu thresholding on HSV saturation — the
textbook approach for whole-slide thumbnails. It failed badly here: on this
dataset, Otsu's threshold tracked staining intensity, not tissue presence
(chosen threshold rose from ~0.12 on faint patches to ~0.43 on strongly
stained ones), so weakly-stained tissue was silently excluded from its own
denominator and every percentage was inflated in a way that was invisible in
the final numbers. This was **measured, not assumed** — the docstring in
`tissue.py` carries the actual numbers.

The fix: detect tissue by **optical density** (mean absorbance across RGB),
which responds to *any* stain absorbing light. Saturation-based detection is
kept (`method="saturation"`) because it is still right for low-magnification
thumbnails, where the field is mostly glass; it is simply wrong for patch-level
40× IHC, where the field is already almost all tissue.

### The classical baseline (`preprocessing/baseline.py`)

`intensity_map()` thresholds the DAB optical density into five classes —
background, negative, weak (1+), moderate (2+), strong (3+) — at fixed cut
points (`dab_od_weak=0.25`, `dab_od_moderate=0.50`, `dab_od_strong=0.80`,
configurable in `configs/preprocessing.yaml`). This module plays **three
different roles**:

1. It is the **pseudo-label generator** Phase 2 trains on (there are no
   pixel-level pathologist annotations for this project).
2. It is the **experimental control**. Because the deep model learns from
   these exact thresholds, the model agreeing with them proves nothing — it
   is carried through evaluation as a baseline so the deep model's actual
   contribution is measurable rather than assumed. (Measured: the shipped
   model scores almost exactly what the rule scores, 76.0 % vs 75.0 %
   in-domain and 39.9 % vs 39.6 % on BCI — which is why v2 exists.)
3. It is the **area-percentage engine** (`area_distribution`) reused
   everywhere a percentage is reported.

Percentages are always **of tissue area**, with background explicitly
excluded from the denominator — deliberately not CAP/ASCO's percentage of
*tumour cells*, and every artifact that reports one says so.

### Tiling (`preprocessing/tiling.py`)

Splits a large image into fixed-size tiles, tracking each tile's position in
**both** the working (possibly downsampled) frame and the original image
frame, because a coordinate error in stitching is silent — the heatmap just
ends up subtly, undetectably wrong. Downsampling is by **strided
subsampling, never averaging**, because averaging would blend stained and
unstained pixels and shift the optical densities the classes are defined on.

---

## Phase 2 — Segmentation training (`training/`, `models/`)

### The data problem: no pixel annotations exist

There are no pathologist-drawn pixel masks anywhere in this project. The
dataset gives one HER2 score per *patch* (its folder) and one per *source
slide* (its filename). So the dense per-pixel targets the segmentation model
trains on are **pseudo-labels**: literally the output of the Phase 1
classical thresholder, cached to disk as PNGs precisely so they can be
inspected and disputed rather than trusted blindly (`training/pseudo_labels.py`).

Consequences that are load-bearing for how every result must be read:

- **Circularity.** A model trained on these targets that then agrees with
  them has demonstrated nothing; the classical thresholder is the control.
- **A ceiling.** What a learned model can add is spatial coherence and
  robustness to illumination/stain drift — those are the things worth
  measuring. (The v2 multi-task model additionally learns from the real
  0/1+/2+/3+ labels; see below.)

The targets were sanity-checked before anything was trained on them: mean
stained tissue area rises **monotonically** with the dataset's own patch
label (0 → 1+ → 2+ → 3+), at both magnifications tested.

### The split problem: no slide identifiers

The project brief requires that patches from one slide never straddle the
train/validation boundary. That guarantee is **impossible on this dataset**:
filenames carry no slide ID, and the coarsest available grouping (8 groups)
is almost perfectly confounded with the label itself.

`training/splits.py` does the next-best thing:

- The **held-out set** is defined by the `_train_` / `_test_` token baked into
  each filename (inferred to be the dataset authors' own split — the
  `train/`/`test/` *directories* were measured to cross this token, so holding
  them out would leak).
- The **validation set** is a stratified random draw from the rest, explicitly
  labelled `leakage_free=False` — used only to pick a stopping epoch.
- A correct, group-respecting `grouped_split()` exists and is tested, ready for
  real slide IDs.

Both caveats are written into every artifact a run produces. One real
guarantee **is** enforced: a 1024×1024 patch cut into four 512×512 tiles
produces near-duplicate tiles, so the split is drawn over **source patches**
first and expanded to tiles afterwards (`_assert_no_parent_overlap`).

The **held-out set is never evaluated during development** — a held-out number
that gets watched stops being held out.

### Model (`models/unet_seg.py`)

**ResNet18 encoder + U-Net decoder, 4 input channels (RGB + the DAB
optical-density channel).** The DAB channel is a deliberate inductive bias: the
pseudo-labels are a function of DAB OD, so handing the model that quantity,
rather than making it re-derive it from RGB, helps a weakly-supervised setting
with very little signal for the rarest class. The first convolution's extra
channel is initialised from the mean of the pretrained RGB weights.

*History.* Phase 2 first used SegFormer-B0. Its decode head predicts at H/4,
so the thin membrane rims the classes are made of were sub-pixel before they
reached the loss. Moving to native 40× fixed weak (1+) (IoU 0.030 → 0.341) but
moderate (2+) stayed at ~0.0001. Phase 5 compared a U-Net head-to-head on
identical data and split (below); U-Net won on every class and **SegFormer was
removed from the codebase** (`models/segformer_seg.py` no longer exists;
`select_architecture` recognises only `"unet"`, and says why if asked for
SegFormer).

### Loss (`training/losses.py`)

**Cross-entropy + soft Dice**, weighted 1.0 / 0.5 (focal loss is available).
The class distribution is severely skewed; plain CE's cheapest route to a low
average is to never predict the rare classes. Dice is averaged over classes
present in the batch — **absent classes are excluded, not scored as 0 or 1**.
`class_weights: "auto"` resolves to inverse-frequency weights *before* the loss
is built, and the loss refuses to run if it ever receives the literal string
`"auto"`.

### Training loop (`training/train.py`)

Every run writes, as plain files: resolved config, exact split with caveats,
per-epoch CSV, per-class metrics and confusion matrix, the best checkpoint, and
`run_summary.json`. **Model selection is on tissue mean IoU** (the four staining
classes weighted equally), not validation loss or overall mIoU, which is
dominated by the easy background class. Metrics are accumulated into **one
confusion matrix over the whole split**, and absent classes are reported as
`None`, not `0`.

Augmentation is restricted to the eight dihedral transforms; colour jitter or
arbitrary rotation would shift the DAB densities the labels are defined on or
invent classes by interpolating the label map. (The v2 model, whose labels do
not depend on exact DAB values, does use stain augmentation.)

### The training pool is whatever tiles are on disk

`training/train.py` caps its fit/validation samples with `stratified_subsample`
drawn from the patches that have tiles in the cache *at that moment*. A cache
that grows between runs changes which patches the second run trains on, with the
same seed and config. That happened here (cache built 2026-08-06 with 3,526
tiles gained 3,662 more on 2026-09-17). The baseline and class-weighted runs
train on 792 tiles / validate on 119; the ordinal run on 786 / 116 (different
patches). The check is one log line: `fit: 200 patches -> 792 tiles`.
`data/cache/pseudo_labels_40x_orig` reproduces the baseline sample exactly. New
tiles go into a cache of their own, never into a training cache. A second
consequence: the cache's holdout patches are almost exactly the calibration half
of the conformal split (285 vs 13), which is why the September pixel-level
conformal evaluation had only 52 test tiles.

### Resolution and the three levers on moderate (2+)

* **Run 1, effective 20×:** weak 0.030, moderate 0.000 despite pixel accuracy
  0.81 (proof that pixel accuracy is the wrong number). Thin rims were
  sub-pixel at H/4.
* **Run 2, native 40×** (four 512 tiles per patch, `tiling.downsample: 1`):
  weak ×11, tissue mIoU +33 %; moderate still ~0.0001.
* **Phase 5 (ResNet18-UNet, same data/split/seed):**

  | class | SegFormer | U-Net | Δ |
  |---|---|---|---|
  | negative | 0.815 | 0.839 | +0.024 |
  | weak (1+) | 0.341 | 0.666 | +0.325 |
  | **moderate (2+)** | **0.00006** | **0.589** | **+0.589** |
  | strong (3+) | 0.618 | 0.891 | +0.273 |
  | tissue mean IoU | 0.443 | **0.746** | +0.303 |

  This reversed the working hypothesis that the failure was a data/label ceiling:
  it was architecture-specific (decode resolution) and, partly, data volume.
* **Three cheap levers on moderate**, each with its decision rule fixed
  beforehand: inverse-frequency class weights (`PHASE5_CLASS_WEIGHTS.md`,
  **rejected**), an ordinal-distance auxiliary loss (`PHASE5_ORDINAL.md`,
  **rejected**, moderate ended below baseline), and 8 instead of 4 epochs
  (`PHASE5_8EPOCHS.md`, **adopted**: moderate 0.589 → 0.657, every class
  improved). **Adopted as the default on 2026-10-06:** `configs/training.yaml`
  now trains 8 epochs into `artifacts/phase2_unet_8epochs`, which the server,
  Docker, `serve.bat`, the conformal scripts and `scripts/package_models.sh` load by
  default. Its pixel-level conformal calibration was rebuilt for that checkpoint
  (`scripts/calibrate_conformal.py`: the server refuses a calibration made for another
  checkpoint), the checksum manifest was regenerated, and the server was started on it.
  The old 4-epoch default is kept unchanged as `configs/training_baseline_4epochs.yaml`
  (output `artifacts/phase2_unet`) so the baseline in `PHASE5*.md` stays reproducible.
* **Membrane completeness as a proxy** (`PHASE5_MEMBRANE_COMPLETENESS.md`)
  was prototyped offline and is mostly negative: about a third of validation
  tiles have no moderate class and score IoU 0.0 mechanically, which produced
  most of the proxy's apparent correlation.

---

## The stain map and the v2 pre-score model

### Why v2

The shipped segmentation model scores almost exactly what the DAB rule scores
(76.0 % vs 75.0 % in-domain; 39.9 % vs 39.6 % on BCI), and it trained on 200 of
7,729 available patches (a CPU limit). **v2** (docs/V2_TRAINING_PLAN.md) changes
what the network learns from and how much it sees:

* a score head on the U-Net encoder, trained on the real 0/1+/2+/3+ labels,
  with attention pooling over all tiles of a patch/case (`models/multitask.py`);
* ResNet-50 encoder with pathology self-supervised weights (Lunit,
  Kang et al., CVPR 2023);
* all 7,729 fit patches; stain/zoom/blur/noise augmentation on the GPU
  (`training/gpu_ops.py`); a multi-site option (our data + BCI train);
* the segmentation decoder is still trained on the pseudo-label rule so the
  viewer's explainable intensity map is preserved;
* budget guards (wall-clock cap, per-epoch checkpoints with resume, throughput
  guard, auto-stop pod). Targets and protocol were written **before any GPU
  run** and not changed afterwards. Hard budget $6.72.

### Results (held-out; never used for selection)

| Run | Data | In-domain (HER2_IHC_40X holdout) | BCI test |
|---|---|---|---|
| A | our data only | 88.7 %, QWK 0.965 | **unseen site:** 48.3 % raw, 54.5 % site-normalised, QWK ~0.31–0.33 |
| **B (deployed)** | our data + BCI train | **92.3 %, QWK 0.975** | 75.3 %, QWK 0.698 (a *seen* site, new images) |
| C | BCI only | — | 58.8 % / our holdout (unseen) 67.3 %, QWK 0.717 |

Reading these honestly: the in-domain target (>90 % accuracy, QWK ≥ 0.90) was
met by Run B; Run A missed the accuracy target by 1.3 points. The **unseen-site
target (>80 %) was missed** — at a hospital the model never trained on, accuracy
fell to ~48–55 %. Errors are almost all 0↔1+ and 1+→2+, the boundaries
pathologists also disagree on most. The cell-level ASCO/CAP rule on the holdout
reaches 72.0 % accuracy / QWK 0.844 (recall 0/1+/2+/3+ = 64/52/76/96 %).

Experiments that did **not** close the cross-site gap are recorded rather than
dropped: label-free site adaptation (BatchNorm adaptation hurt, QWK 0.33 → 0.23;
self-training fixed the "never predicts 1+" failure, 1+ recall 2 % → 42 %, but
did not improve QWK), 25-case few-shot calibration (unreliable: 31–58 %
depending on the draw), training in a shared stain space (hurt unseen-site
accuracy), and per-slide control calibration (recovers most run-to-run loss for
threshold scoring in simulation; the network is already robust to that variation).
Run B is the safety gate's reference: the gate exists *because* of these results.

### Cell-level ASCO/CAP evidence (`app/cells.py`)

Every detected cell is classified by membrane completeness and intensity; the
10 % rule gives the category, with HER2-low / ultralow notes. Cut points were
calibrated on 80 training-split patches (`scripts/calibrate_cells.py`,
`configs/cell_params.json`) and the held-out figure measured once. Limits: field
level (every detected cell counts: tumour is not segmented),
and cut points are calibrated against patch labels, not pathologist cell
annotations.

---

## Cross-institution stain shift (Objectives 1 and 2)

The Phase 4 numbers in this section **supersede** the September smoke-scale
write-up (computed with the buggy stain estimator on 52 patches).

### Objective 1 — adaptive stain-vector analysis

Per-image Macenko stain vectors (corrected estimator). Across 100 images per
source (`scripts/stain_variation_sites.py`): stain *directions* differ between
institutions by 3–5× the variation inside one institution or one slide
(e.g. training site vs BCI: haematoxylin 15.9°, DAB 8.4°; training site vs the
ACROBAT slide: DAB 27.8°), and counterstain strength differs about 3-fold.
Between-group distance exceeds within-group spread in the training data too
(1.42×, groups being confounded with HER2 score because no slide IDs exist).

`evaluation/stain_shift.py` turns a stain descriptor into a similarity weight;
`evaluation/stain_variation.py` reports the same quantity as a variation
summary, so a calibration weight and a reported "distance" are literally the
same number. `evaluation/cross_site.py` provides **site-level** stain profiles
and normalisation (one Macenko matrix and concentration scale per institution,
from unlabelled images), which — unlike per-image methods — preserves the DAB
difference between a 0 and a 3+ case. Normalisation recovers about 10 points of
four-class accuracy on BCI but does not close the gap
(docs/CROSS_SITE_STAIN_NORMALIZATION.md); it *hurts* once a model has trained on
the site's raw colours.

### Objective 2 — stain-shift-weighted conformal prediction

`evaluation/cross_site_conformal.py`, `scripts/conformal_cross_site.py`
(results in `artifacts/conformal_cross_site/`). LAC score on the image-level
HER2 grade; calibration on 951 held-out training-site images; tests on 953
same-hospital and 338 BCI images. Coverage at the other hospital, target 95 %:

| Method | Run A (BCI never seen) | Run B (deployed) |
|---|---|---|
| unweighted | 58.9 % | 82.2 % |
| **stain-shift weighted (the project's method)** | 63.6 % | **91.7 %** |
| likelihood-ratio weighted (Tibshirani et al.) | 99.7 % (set size 3.9 of 4) | 99.1 % |
| calibrated on 25 local cases | 95.9 % (set size 3.8) | **95.9 % (set size 2.1)** |

Standard conformal prediction **loses its guarantee** under real
cross-institution shift (95 % promised, 59–82 % delivered). Stain-shift weighting
improves coverage (82 % → 92 %) **but does not fully restore it**: part of the
shift is in how institutions grade (concept shift), which no covariate weighting
can correct. Likelihood-ratio weighting restores validity only by returning
nearly every grade (the two institutions' stains are almost perfectly separable,
domain AUC 0.999, effective calibration size 2). Calibrating on ~25 local cases
restores the guarantee with informative sets. In the product, the 90 % conformal
set (`app/prescore.prediction_set`, `scripts/calibrate_prescore_sets.py`) is
shown only at the site it was calibrated for.

### Objective 3 — ASCO/CAP mapping and agreement

`evaluation/cap_mapping.py`. Against the datasets' expert labels: HER2-IHC-40x
holdout 92.3 % / QWK 0.975 (n = 1,904); BCI test 75.3 % / QWK 0.698 (n = 977).
Agreement with *this project's own pathologists* uses the review log
(`artifacts/reviews.jsonl`, `scripts/evaluate_cap_agreement.py`): **zero real
reviews exist**, so that number cannot be reported yet.

---

## The application

### Backend (`app/`)

`app/server.py` uses `http.server.ThreadingHTTPServer` — no Flask, no FastAPI, no
CDN, nothing fetched from the internet at runtime — because the machines this
must run on are hospital and college computers where installing a framework is
friction. It binds to `127.0.0.1` by default and warns loudly otherwise.
Uploads are capped; static-file and sample-file readers independently guard
against path traversal.

| Module | Role |
|---|---|
| `analysis.py` | `Analyzer`: loads the checkpoint once, tiles an image of any size (edge-replicate padding), stitches, restricts the model's prediction to the **same tissue mask** the baseline uses so the two columns share one denominator; images downscaled for transport by nearest-neighbour only so no in-between class colour is invented |
| `prescore.py` | the AI pre-score (grade, probabilities, borderline flag), 90 % prediction set, Grad-CAM evidence, per-region pre-scores and heterogeneity |
| `cells.py` | cell-level ASCO/CAP evidence and membrane map |
| `guidance.py`, `decision.py`, `explain.py` | ISH guidance and decision support, explanations (below) |
| `report.py` | PDF report (ReportLab) incl. sign-off block |
| `review_record.py` | pathologist review record (below) |
| `auth.py`, `admin_cli.py` | accounts, sessions, admin console (below) |
| `learning/` | continual learning loop (below) |

### The portal (`ui/`)

A React portal (built into the Docker image; the `biomark` command builds
`ui/dist` on first run) with pages for field analysis, whole slides, cases,
dashboard, pathologist review, method/model card, profile and the admin
console. Class maps use a colour-blind-safe, monotonically darker palette so
ordering survives greyscale printing. Image **Enlarge** is a real zoom/pan
viewer (OpenSeadragon); layout was audited at 100/125/150/200 % browser zoom.

Framing decisions are literal test assertions, because they are what a
well-meaning UI tweak is most likely to erode: the model is **never shown
without the classical baseline** (agreement with the rule it was trained to
imitate is not clinical accuracy); the moderate (2+) row is flagged **in the
table itself**, not only in a footnote; a pre-score is never a verdict.

### ISH decision support and explanations (`docs/ISH_DECISION_SUPPORT.md`)

The panel follows the order in which a pathologist decides on ISH: the ASCO/CAP
algorithm with this case's step lit; weighted evidence for and against ISH; a
field-quality checklist (focus calibrated on held-out fields, tissue %, cell
count, magnification, site validation, AI–cell agreement, heterogeneity,
control reminder); each decisive share with its 95 % Wilson interval against
the 10 % line; sensitivity of the grade under 27 nearby cut-point combinations;
the exact cell counts that would change the grade; and where to score ISH.
Clinical rules worth knowing: **0 vs 1+ is not an ISH question** (it decides
HER2-low eligibility and is flagged separately); **too few cells is a quality
failure, not a reason for ISH**; a 3+ goes to "ISH recommended" only for reasons
that question the grade, never for cell count alone.

### Pathologist review (`docs/PATHOLOGIST_REVIEW.md`)

One record per save, appended and never edited: specimen and pre-analytics
(fixation, cold ischaemia, clone), controls and adequacy, the HER2 assessment
(score, ultralow flag, ASCO/CAP category, cell percentages, heterogeneity,
artefacts), agreement with the AI (a reason is required to disagree), decision
and follow-up, and a snapshot of what the system showed. Status moves
draft → preliminary → final; a final report needs an attestation and is changed
only by an **amendment** with a stated reason (a new version pointing at the old
one). No final score on tissue marked inadequate; percentages cannot exceed
100 %.

### Accounts and the admin console (`docs/ACCOUNTS_AND_ADMIN.md`)

Three roles enforced on every API route: **Administrator**, **Pathologist**
(analyse, record assessments, mark regions, download reports) and **Viewer**
(analyse, download). SQLite (standard library); passwords hashed with scrypt
(N=2¹⁴, r=8, p=1) with per-password salts; sessions are random 256-bit tokens in
`HttpOnly; SameSite=Strict` cookies with only the SHA-256 stored; CSRF token on
every state-changing request; per-account lockout and per-IP throttling;
identical answers for wrong password and unknown email; the last administrator
cannot be demoted, disabled or deleted; one-time links are stored as hashes.
The console covers users, access requests, sessions, an audit log with export,
settings (timeouts, password policy, lockout) and deployment readiness. First
run prints a one-time setup link to create the first administrator.

### Whole slides (`wsi/`, `docs/WHOLE_SLIDE.md`)

A scanned slide (`.svs`, `.ndpi`, `.tiff`, `.mrxs`) is browsed at full
resolution and analysed: it is read **in µm/px, not pyramid levels** (so
different scanners are resampled to one scale); tissue is found on an 8 µm/px
overview; **blue ink / mounting film** (a colour check block by block, no model) and
**on-slide control cores** (small, compact pieces standing ≥1.5 mm from the main
tissue) are excluded and drawn on the overlay; up to 40 fields are spread over the
remaining tissue; cell-level ASCO/CAP evidence is counted per field; a slide-level
pre-score comes from attention pooling over all tiles, with heterogeneity and
hotspots; the same site gate applies. Slides coarser than 0.5 µm/px (below ~20×)
**never get a pre-score**.

**Tumour is not segmented.** An invasive-tumour segmenter (a ResNet-50 U-Net trained on
TIGER H&E, haematoxylin channel only) was built and then **removed on 2026-10-06**: it is
not one of the four objectives, it never saw a HER2 IHC tumour annotation, and it did
not separate DCIS or healthy glands from invasive tumour (IoU 0.00 for both; invasive
tumour IoU 0.67). Fields are therefore chosen over all usable tissue, so stroma,
in-situ carcinoma and normal ducts can be counted; every slide result says so and the
pathologist confirms that each field lies in invasive tumour. The git history keeps the
code; the weights file `artifacts/tumour/best.pt` is left on disk, unused and no longer
packaged.

**On-slide control calibration.** The control's DAB optical density is measured on every
slide that has one. It is **used** only when the laboratory declares the control's level
(`--control-level 3+`) and a reference signature exists
(`configs/control_reference.json`, built by `scripts/build_control_reference.py`; the
default is a proxy made of 3+ patient patches of the training site, so a hospital should
build its own from its own control). The strongest core's p90 is compared with the
reference and the slide's DAB is rescaled by that gain, **for the threshold-based cell
evidence only**; implausible gains (outside 0.33–3.0) are refused and flagged. Without a
declaration the control is reported, never applied. Tested on synthetic slides; not yet
validated on a real hospital's controls.

On the real 10× ACROBAT slide three safety problems were found and fixed (on-slide HER2
**control cores** counted as the patient's — now detected and excluded; blue ink/film at
the coverslip edge flagged as artefact; an unassessable 10× slide receiving "ISH not
indicated", now "not assessable at this magnification"), and a server bug where renaming
the site kept the training site's validation record, so any hospital looked validated,
was fixed with a regression test.

### Continual learning (`app/learning/`, `docs/LEARNING.md`)

Every analysed case is stored; signed (final) pathologist reviews become labels
and region annotations become tile labels; a **candidate version** is trained on
demand (only the attention pooling and score head, ~66 k parameters, on frozen
features, with training-site replay, class balancing and an anchor penalty) and
judged against **gates fixed in advance** (≥40 signed cases and ≥3 per grade;
no forgetting on a locked reference set; ≥2 points of real local gain by
5-fold cross-validation; no new two-grade errors). Passing makes a version
*eligible*; **an administrator must activate it** (audited), and any earlier
version can be re-activated. It deliberately does not update itself after every
slide: a model that changed its own weights automatically could be shifted by
one mislabelled case with nobody able to say which model produced which report.
Activating a version switches the prediction sets off until they are
recalibrated on signed local cases; the admin page now does this in one audited
step (**Learning -> Prediction sets -> Recalibrate**), needing at least 25 signed
cases (`calibration.min_cases`), keeping the previous file, and storing 1.0 (every
grade) for any level the data cannot support.

### Deployment (`docs/DEPLOYMENT.md`)

One Docker container serves the whole system (multi-stage image that builds the
portal, non-root user, health check, `docker-compose.yml`). Models are mounted,
not baked in (`scripts/package_models.sh` → a bundle with a SHA-256 manifest).
Minimum 4 CPU cores / 8 GB RAM, no GPU; a field takes ~20–30 s and a whole slide
~10–15 min on 4 cores. Patient images and records never leave the server. CI
builds the image from a clean checkout and checks that the server and every
dependency load inside it; two defects found that way on 2026-10-03 (the image
omitted `wsi/`; `requirements.txt` omitted OpenSlide) are fixed. The hosting
site is a hospital decision.

---

## Testing philosophy

Two different kinds of thing are tested. Ordinary correctness (overlays keep
their class values, tiled prediction covers the whole image, splits contain no
leaked patches, weights resolve to the right length) is tested the normal way.
**Framing constraints** are tested just as literally: that no verdict field can
appear, that the pre-score is withheld at an unvalidated site, that the review
step cannot fire without an explicit submit, that the 2+ class is flagged in the
rendered output, that the on-slide control is never used without a declared level, that a
validation record counts only for the site it names. These are load-bearing
specification, not decoration.

The suite lives in ~40 files under `tests/`. On 2026-10-06 `pytest -q` gave **514 passed, 0 skipped**
(about 9 minutes on a CPU laptop). Two environment traps are worth knowing: a third-party package in
site-packages can ship its own top-level `tests` package and shadow this folder (fixed by
`tests/__init__.py`), and the whole-slide tests are skipped silently if OpenSlide
(`openslide-bin`, `openslide-python`, both in `requirements.txt`) is not installed, as is `pypdf`
for the report tests. Earlier counts in older copies of this document (154, 280, 408) were snapshots
from earlier phases.

---

## Reproducing this project end to end

```
# Phase 1 sanity check
python scripts/sanity_check_phase1.py

# Build the pseudo-label cache (native 40x; downsample:1 in configs/preprocessing.yaml)
python scripts/build_pseudo_labels.py --limit 900 --preview 8

# Train the stain map
python scripts/train_phase2.py --config configs/training.yaml
python scripts/plot_training.py --run artifacts/phase2_unet
python scripts/predict_preview.py --run artifacts/phase2_unet --count 8

# Evaluation (Phase 4)
python scripts/stain_variation_sites.py
python scripts/conformal_cross_site.py
python scripts/evaluate_cap_agreement.py

# v2 (GPU pod workflow): docs/V2_TRAINING_PLAN.md; whole slides: docs/WHOLE_SLIDE.md

# Tests
pytest -q

# Launch the portal (builds ui/dist the first time; prints a one-time admin setup link)
biomark            # or: python -m app.server --run artifacts/phase2_unet
# then open http://127.0.0.1:8000     (Docker: docs/DEPLOYMENT.md)
```

`configs/preprocessing.yaml`'s `tiling.downsample` controls magnification
(`1` = native 40×, `2` = effective 20×); `configs/training.yaml`'s
`data.cache_root` must point at a cache built with the matching setting.

---

## Where the project actually stands

The four objectives of the project (PHASE4.md, "Final status", 2026-10-03):

| # | Objective | Status |
|---|---|---|
| 1 | Adaptive stain-vector analysis of stain variation across slides | **Done** (Macenko estimator, corrected 2026-10-01) |
| 2 | Stain-shift-weighted conformal prediction under cross-institution shift | **Done**, evaluated on a real second institution; improves coverage (82 % → 92 % at a 95 % target) but does **not** fully restore it |
| 3 | Map AI predictions to ASCO/CAP; agreement with expert ground truth | **Done** against the datasets' expert labels; agreement with local pathologists waits on real reviews |
| 4 | Complete HER2 AI system with web interface and Docker | **Done and deployment-ready** (hosting is a hospital decision) |

**Done and defensible:** Phase 1 preprocessing (measured, not assumed, at every
stage that could silently go wrong); the segmentation pipeline and an honest
account of the dataset's limits (pseudo-labels, no slide IDs); the architecture
decision (ResNet18-UNet over SegFormer, moderate 2+ IoU 0.00006 → 0.589 → 0.657
with 8 epochs); the v2 multi-task pre-score model (92.3 % / QWK 0.975 in-domain)
behind a site safety gate; cross-institution conformal prediction and stain
analysis; cell-level ASCO/CAP evidence; ISH decision support; whole-slide
analysis (tissue, ink and control-core exclusion, control calibration; tumour is not segmented); accounts, audit and an admin console; the
pathologist review record; a gated continual-learning loop; Docker packaging
verified in CI.

**Honest limits, stated plainly:**

* **Unseen-site accuracy is low.** At a hospital the model never trained on,
  accuracy was 48–55 % (the in-domain 92.3 % does not transfer). This is the
  reason the pre-score is withheld until a site is validated, and why 25 local
  cases do not reliably fix it.
* **Stain-shift weighting helps but does not restore coverage** (91.7 % at a
  95 % target for the deployed model).
* **Pseudo-labels and an inferred split** remain the basis of the segmentation
  model; the validation split is leaky by construction.
* **Whole-slide fields are not restricted to tumour.** Tumour is not segmented, so stroma,
  in-situ carcinoma and normal ducts can be counted; the pathologist confirms the scored area.
* **Control calibration is unvalidated on real controls**, and its default reference is a proxy.
* **Moderate (2+) is the weakest class** for the stain map (IoU 0.657 with 8
  epochs) and is flagged in the interface.
* **No real pathologist reviews exist** (`artifacts/reviews.jsonl` is empty of real
  entries) and **no ≥20× HER2 whole slide** has been analysed; Kottayam slides
  are still not digitised. These are blocked on data, not engineering.
* **Not a certified medical device.**

**Small open follow-ups:** run 5–10 Kottayam slides in shadow mode for a pathologist to
check the exclusions and fields; build a Kottayam-specific control reference
(`scripts/build_control_reference.py --images ...`) and validate the control calibration
on its control slides; re-time whole-slide analysis on the target hardware; delete the
unused `artifacts/tumour/` weights when no longer wanted.
