# BioMarkHER2 — Implementation Notes

A complete account of what has been built, why each piece exists, and how the
pieces fit together. Written so that someone who was not in the room for any
of the decisions — a teammate, an examiner, a future version of you six months
from now — can pick this up and understand not just *what* the code does but
*why* it does it that way.

If you only read one section, read [The one rule everything else follows](#the-one-rule-everything-else-follows)
and [Where the project actually stands](#where-the-project-actually-stands).

---

## What this is

BioMarkHER2 is an AI-assisted **quantitative measurement tool** for HER2
immunohistochemistry (IHC) slides, built as a final-year academic project with
Kottayam Medical College as the clinical reference point. Pathologists score
HER2 IHC on a 0 / 1+ / 2+ / 3+ scale based on membrane staining intensity and
completeness, and the 2+ ("equivocal") category triggers a second, more
expensive FISH test. The tool's job is to look at a stained field and report,
per intensity class, how much of the tissue area is stained at that level —
a *measurement*, handed to a pathologist, not a verdict.

There is no whole-slide-image data available yet — no scanner, no real
patient slides. Everything so far has been built and validated against a
public patch-level dataset (**HER2_IHC_40X**, ~11,000 pre-cut 1024×1024 IHC
patches with one HER2 score per patch), used as an approved stand-in until
real Kottayam slides arrive. That substitution, and the fact that this machine
is CPU-only with no GPU, shapes almost every engineering choice below.

## The one rule everything else follows

> Correctness, interpretability, and defensibility of every result matter
> more than speed of delivery. This is a **pre-scoring assistive tool** that a
> pathologist reviews and confirms — never an autonomous final-scorer.

Concretely, that rule has been enforced as actual code and actual tests, not
just as a sentence in a document:

- **No code path anywhere produces a field called `score`, `her2_score`,
  `verdict`, or `diagnosis`.** `tests/test_app.py` asserts this by scanning
  the JSON the server returns.
- **A human-review step is mandatory and cannot fire automatically.** The
  review UI only submits on an explicit form `submit` event, requires a
  reviewer identity, and offers "cannot assess from this field" as a first
  class option — forcing a choice would manufacture agreement nobody actually
  gave.
- **Every number that could be misread is labelled with what it actually is**,
  inline, not in a footnote: pseudo-labels vs. pathologist annotations,
  tissue-area percentage vs. CAP's tumour-cell percentage, and the model's
  specific, current failure to predict the 2+ class.
- **Nothing is thrown away that would make a result hard to audit later.**
  Every run writes its resolved config, its exact data split (with caveats),
  per-epoch metrics, a confusion matrix, and the checkpoint, all as plain
  files — openable a year from now without this environment.

---

## Project layout

```
preprocessing/    Phase 1 — pixel-level image processing, stain math, the classical baseline
training/         Phase 2 — dataset construction, splits, model, losses, training loop
models/           the SegFormer wrapper
app/              the review-viewer frontend (Phase 2's demo surface)
configs/          YAML configs — one file fully describes one run
scripts/          CLI entry points that call into the packages above
tests/            154+ tests; the project's actual specification in executable form
artifacts/        everything a run produces (not source — regenerable)
data/             raw dataset + cached pseudo-label targets
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
and the frontend calls Phase 1 live on every upload.

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

Stain **normalization** (Macenko or Reinhard, `apply_normalization`) is
implemented but **defaults to off** — the substitute dataset is single-source,
so there is no inter-scanner colour variation to correct, and normalizing
would silently shift the exact DAB optical densities the thresholds below are
defined on. It is there and tested for when genuinely multi-source (multi-
scanner Kottayam) data arrives.

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
which responds to *any* stain absorbing light, not to which stain or how
much. Saturation-based detection is kept available (`method="saturation"`)
because it is still the right tool for low-magnification thumbnails, where
the field is mostly glass and Otsu has a real boundary to find; it is simply
wrong for patch-level 40× IHC, where the field is already almost all tissue.

### The classical baseline (`preprocessing/baseline.py`)

`intensity_map()` thresholds the DAB optical density into five classes —
background, negative, weak (1+), moderate (2+), strong (3+) — at fixed cut
points (`dab_od_weak=0.25`, `dab_od_moderate=0.50`, `dab_od_strong=0.80`,
configurable in `configs/preprocessing.yaml`). This module plays **three
different roles** and it matters which one is in play at any given moment:

1. It is the **pseudo-label generator** Phase 2 trains on (there are no
   pixel-level pathologist annotations for this project — see Phase 2 below).
2. It is the **experimental control**. Because the deep model learns from
   these exact thresholds, the model agreeing with them proves nothing — it
   has to be carried through to Phase 4 evaluation as a baseline so the deep
   model's actual contribution is measurable rather than assumed.
3. It is the **area-percentage engine** (`area_distribution`) reused
   everywhere a percentage is reported, including in the frontend.

Percentages are always **of tissue area**, with background explicitly
excluded from the denominator — deliberately not CAP/ASCO's percentage of
*tumour cells*, and every artifact that reports one says so.

### Tiling (`preprocessing/tiling.py`)

Splits a large image into fixed-size tiles, tracking each tile's position in
**both** the working (possibly downsampled) frame and the original image
frame. This bookkeeping matters because Phase 3 will need to stitch
per-tile predictions back into a whole-slide map, and a coordinate error
there is silent — the heatmap just ends up subtly, undetectably wrong.
Downsampling is by **strided subsampling, never averaging**, because
averaging would blend stained and unstained pixels and shift the optical
densities the classes are defined on.

---

## Phase 2 — Model and training (`training/`, `models/`)

### The data problem: no pixel annotations exist

There are no pathologist-drawn pixel masks anywhere in this project. The
dataset gives one HER2 score per *patch* (its folder) and one per *source
slide* (its filename). So the dense per-pixel targets the segmentation model
trains on are **pseudo-labels**: literally the output of the Phase 1
classical thresholder, cached to disk as PNGs precisely so they can be
inspected and disputed rather than trusted blindly
(`training/pseudo_labels.py`).

This has two consequences that are load-bearing for how every later result
must be read:

- **Circularity.** A model trained on these targets that then agrees with
  them has demonstrated nothing. The classical thresholder must be carried
  through Phase 4 as a control; if the deep model does not beat it, that is
  the honest finding.
- **A ceiling.** The thresholder can't be exceeded on its own terms. What a
  learned model can actually add is spatial coherence (thresholding is
  per-pixel and noisy; a segmentation model sees neighbourhoods) and
  robustness to illumination/stain drift — those are the things worth
  measuring.

The targets were sanity-checked before anything was trained on them: mean
stained tissue area rises **monotonically** with the dataset's own patch
label (0 → 1+ → 2+ → 3+), at both magnifications tested, which is the
signature of a deconvolution and threshold set that behaves sensibly.

### The split problem: no slide identifiers

The project brief (correctly) requires that patches from one slide never
straddle the train/validation boundary — otherwise validation scores
memorisation, not generalisation. That guarantee is **impossible on this
dataset**: filenames carry no slide ID, only a sparse global counter, and the
coarsest available grouping (slide-score × origin directory, 8 groups) is
almost perfectly confounded with the label itself — holding out any one group
removes an entire intensity class from training.

`training/splits.py` documents this at length and does the next-best thing
that's actually available:

- The **held-out set** is defined by the `_train_` / `_test_` token baked
  into each filename (inferred to be the dataset authors' own split — the
  `train/`/`test/` *directories* were measured to cross this token in both
  directions, 78% of `test/`'s files are named `_train_`, so the directories
  are a re-shuffle, not a split, and holding them out would leak).
- The **validation set** is a stratified random draw from the rest, and is
  explicitly labelled `leakage_free=False` — used only to pick a stopping
  epoch and draw curves, never quoted as a generalisation estimate.
- A correct, group-respecting `grouped_split()` function exists and is
  covered by tests, ready for the day real slide IDs (from Kottayam) arrive.

Both caveats (`VAL_LEAKAGE_CAVEAT`, `HOLDOUT_CAVEAT`) are written into every
artifact a run produces — `split.json`, `run_summary.json`, the checkpoint
itself, and every plot — so a number cannot be copied out of this project
without its caveat attached.

One real guarantee **is** available and is enforced: a 1024×1024 source patch
cut into four 512×512 tiles produces near-duplicate tiles, so the split is
drawn over **source patches** first and only then expanded to tiles, checked
by `_assert_no_parent_overlap` on every run.

**The held-out set itself is never evaluated during Phase 2.** It's resolved
and its size recorded, then left alone — a held-out number that gets watched
during development stops being held out, because every epoch/LR/loss-weight
decision starts silently being made against it. It's Phase 4's to spend,
once.

### Model (`models/segformer_seg.py`)

SegFormer-B0 (`nvidia/segformer-b0-finetuned-ade-512-512`), the smallest
SegFormer variant, chosen specifically to be trainable on CPU (3.7M trainable
parameters, ~14–21 min/epoch on this dataset). The pretrained ADE20K decode
head (150 classes) is discarded and re-initialised for 5 classes; the encoder
weights are what's actually being reused, and the mismatch is logged loudly
rather than happening silently.

The one subtlety that matters most for everything downstream: **SegFormer's
decode head predicts at H/4 × W/4**, and the wrapper's `forward()` always
bilinearly upsamples back to input resolution before returning, so nothing
outside this one module ever has to remember to do that upsample itself (a
mismatch between what the loss sees and what the metrics see is exactly the
kind of bug that silently corrupts a whole run). This H/4 resolution turned
out to be the central finding of Phase 2 — see below.

### Loss (`training/losses.py`)

**Cross-entropy + soft Dice**, weighted 1.0 / 0.5. The class distribution is
severely skewed (background and negative dominate almost every patch); plain
CE's cheapest route to a low average is to never predict the rare classes at
all, which produces a good-looking pixel accuracy and a clinically useless
model. Dice is computed per class and averaged over classes present in the
batch — **absent classes are excluded from the average, not scored as 0 or
1**, so a 0-score patch correctly containing no strong-staining pixels isn't
penalised or rewarded for a class that was never there.

`class_weights` supports an `"auto"` mode (see the weighted-run experiment
below): the string is resolved to a concrete inverse-frequency weight list
*before* the loss module is built, and the loss module **refuses to run**
if it ever receives the literal string `"auto"` — a fail-loud guard against
silently training unweighted after asking for weights.

### Training loop (`training/train.py`)

Every run writes, as plain files in `output_dir`: the resolved config
(`resolved_config.yaml`), the exact split with its caveats (`split.json`),
a per-epoch CSV (`epoch_log.csv`), per-class metrics and a confusion matrix
for every epoch, the best checkpoint (`best.pt`), and a `run_summary.json`
tying it all together. No dashboard, no external service.

**Model selection is on tissue mean IoU**, deliberately not on validation
loss and not on overall mean IoU. Overall mIoU is dominated by the easy,
huge background class and keeps climbing while the classes that actually
matter clinically stagnate; tissue mean IoU (`ConfusionMatrix.tissue_mean_iou`,
`training/metrics.py`) weights the four staining classes equally, which is
the behaviour actually wanted.

Metrics themselves are accumulated into **one confusion matrix over the whole
split**, not averaged per-batch — a batch with three strong-class pixels
would otherwise get equal say to a batch with a hundred thousand. Classes
that never appear are reported as `None`, not `0`: an IoU of 0 means
"predicted this and got it wrong," an absent class means "there was nothing
to get right," and collapsing the two quietly drags the mean down for the
wrong reason.

Augmentation (`training/dataset.py`) is restricted to the eight dihedral
transforms — flips and 90° rotations, nothing else. Colour jitter, contrast
changes, or arbitrary-angle rotation would all either shift the DAB optical
densities the classes are defined on (mislabelling the augmented pair) or
require interpolating the label map (inventing classes that were never
assigned).

### Run 1 — effective 20× (the failure that set the direction)

500 fit / 120 val patches, 4 epochs, CPU-only. **Weak (1+) and moderate (2+)
were essentially unlearnable** (IoU 0.030 and 0.000) despite a healthy
overall pixel accuracy of 0.81 — proof, concretely, of why pixel accuracy is
the wrong number to trust and tissue mean IoU is the one to read. The
prediction preview showed *why*: predictions were smooth blobs where the
targets are thin membrane lace. The diagnosis: at 20×, a membrane rim is
1–3 pixels wide — **sub-pixel at the H/4 resolution the decode head actually
predicts at.** Large confluent 3+ regions survive because they're big enough;
thin rims cannot.

### Run 2 — native 40× (the fix that followed from the diagnosis)

Same compute, same 512×512 model input — but instead of downsampling a
1024×1024 patch by 2 into one 512 tile, it's cut into **four native-resolution
512 tiles** (`configs/preprocessing.yaml: tiling.downsample: 1`). Every
membrane is now twice as wide in pixels the model actually sees.

Result: **weak (1+) IoU went from 0.030 to 0.341 (×11)**, tissue mean IoU
+33%, and — tellingly — epoch 1 of the 40× run already beat the *entire*
4-epoch 20× run, on 40% of the data. That is the signature of a resolution
problem, not a data-volume problem.

**Moderate (2+) did not move: IoU 0.0001 (253 pixels out of 21 million).**
The confusion matrix shows the moderate row splitting ~26% into weak and
~71% into strong — the model treats 2+ as if it doesn't exist. Full numbers
and the run-by-run comparison table live in `PHASE2.md`.

### The class-weight experiment (in progress)

Two candidate explanations remained for why 2+ specifically still fails at
40×, and they are separable by experiment:

1. Moderate rims are even thinner than weak ones and may still be sub-pixel
   at H/4 even at native resolution (→ fix is supervising at H/4 directly, or
   full-resolution refinement).
2. At 3.6% of pixels, sandwiched between two other classes, cross-entropy
   has little to lose by never choosing it (→ fix is inverse-frequency class
   weights).

`inverse_frequency_weights()` (`training/losses.py`) existed since early
Phase 2 but was never wired up — off by default because on a distribution
this skewed it can destabilise training, and "does it help" was explicitly
left as an empirical question for a run to answer, not a default to flip
silently.

**What was built to run that experiment:**

- `LossConfig.class_weights` accepts a literal `"auto"` in addition to a
  concrete list or `None`.
- `training.train.resolve_class_weights()` turns `"auto"` into the actual
  inverse-frequency list, counted over **every** fit tile (not a sample —
  the weights are part of the experiment's definition, and a value derived
  from a noisy subsample is a number nobody could reproduce), and writes the
  resolved list back into `resolved_config.yaml` so the run is reproducible
  from its own output artifact rather than from whatever happened to be
  cached at the time it ran.
- `SegmentationLoss.__init__` **raises** if it's ever handed the literal
  string `"auto"` — fail loud rather than silently training unweighted.
- `configs/training_weighted.yaml` — byte-for-byte identical to
  `configs/training.yaml` except `loss.class_weights: auto` and
  `output_dir: artifacts/phase2_40x_weighted`, so the comparison is
  controlled. It states the decision rule *in the file, before the run*:
  moderate IoU moving meaningfully off zero means rarity was (at least part
  of) the cause; staying near zero means it wasn't, and the next experiment
  is supervising at H/4 instead.

**Status:** this run is incomplete. Epoch 1 finished and was checkpointed
before the process was interrupted (training has no resume-from-checkpoint
capability — a restart begins again from epoch 0). The completed epoch 1
already shows a real, non-trivial signal:

| class | epoch-1 IoU (weighted) | run-2 best IoU (unweighted, epoch 4) |
|---|---|---|
| moderate (2+) | **0.0849** | 0.0001 |
| weak (1+) | 0.280 | 0.341 |
| background / negative | lower than unweighted at the same point | — |

Moderate moving from *effectively zero* to *0.08 in a single epoch* is
evidence that class rarity is a real contributing cause — though the run is
only ~1.4 of 4 planned epochs, and the other classes are temporarily lower,
which is an expected effect of reweighting the loss landscape early in
training rather than a red flag. This needs a full 4-epoch run before the
decision rule in the config can be applied for real.

---

## The review-viewer frontend (`app/`)

The user asked for this to be "well showable" — demonstrable to the
pathologist stakeholder, not just runnable from a script. It is a complete,
tested, local web application.

### Why a hand-rolled stdlib server

`app/server.py` uses `http.server.ThreadingHTTPServer` — no Flask, no
FastAPI, no CDN, nothing fetched from the internet at runtime. This machine
is a CPU-only laptop, and the machines this is meant to be *shown on*
(hospital and college computers) are exactly the environment where installing
a web framework is friction and an internet dependency is a failure mode.
Everything — HTML, CSS, JS, model, images — is served from local disk.

It binds to `127.0.0.1` by default and prints a loud warning if pointed
anywhere else: this tool displays medical images and records clinical
opinions with no authentication and no transport security, so it is a local
demo and review aid, not a deployable service.

### The analysis engine (`app/analysis.py`)

Deliberately separated from the HTTP layer so it's testable without a server
and reusable by Phase 3 (which will need to call the same per-tile analysis
when it stitches whole slides). `Analyzer`:

1. Loads the trained checkpoint once at start-up (`best.pt` + the training
   config that describes its architecture).
2. `.predict(rgb)` tiles an image of *any* size into the model's native tile
   size, edge-replicate-pads any ragged edge tile (not zero-padding — a
   black margin is a strong artificial edge the model would predict on), and
   stitches the tile predictions back — covering images that aren't an exact
   multiple of the tile size, tested explicitly.
3. `.analyze(rgb)` runs Phase 1 preprocessing and the model side by side,
   then **restricts the model's prediction to the same tissue mask the
   classical baseline uses** — without this, the two columns would be
   measured over different denominators and their percentages would not be
   comparable at all.

Two more things it does on purpose:

- Every rendered image goes through `to_data_uri()`, which downsizes with
  **nearest-neighbour resampling only**. Class maps are colour-coded; any
  smoother resampling (bilinear, etc.) would blend a "weak" colour and a
  "strong" colour into something that visually reads as "moderate" — quietly
  inventing, in the picture, exactly the class the model is known not to
  predict. Tested directly: `test_transport_downscaling_invents_no_classes`
  decodes a downscaled overlay and asserts every pixel is one of the five
  palette colours, nothing in between.
- The colour palette is colour-blind-safe and monotonically darker with
  intensity, so the ordering survives greyscale printing and the two common
  forms of colour vision deficiency.

### The server (`app/server.py`)

Routes: `GET /` (the page), `GET /api/context` (provenance, sample list,
class legend, caveat text, review-choice list), `POST /api/analyze` (patch
id from the dataset, or a base64-uploaded image), `POST /api/review`
(records a pathologist's confirmed score).

Both the sample-file reader and the static-file server independently guard
against path traversal (`root not in path.parents`) — tested with literal
`../../../etc/passwd`-style inputs. Uploads are capped at 24 MB. Reviews are
appended to `artifacts/reviews.jsonl`, one JSON object per line, each
carrying a UTC timestamp and which run produced it — **this file is the
direct input Phase 4 needs** to compute Cohen's kappa between a pathologist's
actual score and the model's measurements, on fields a pathologist actually
looked at.

### The UI (`app/static/`)

Three steps: pick a sample patch or upload an image → see four panels
(original / detected tissue / model intensity map / classical baseline) and
one area-percentage table, model and baseline **always shown side by side,
never one without the other** → an explicit review form.

Three framing decisions are encoded as literal test assertions in
`tests/test_app.py`, specifically because they are the things a future,
well-intentioned UI tweak is most likely to erode by accident:

1. **No score, ever, anywhere in the payload or the page.** The page states
   in words that it does not assign a HER2 score; a person assigns the score,
   and nothing is recorded until they submit the review form themselves.
2. **The baseline is shown every time, not behind a toggle.** The model was
   trained on the baseline's own output, so agreement between them is
   agreement with the rule the model was trained to imitate — not evidence
   of clinical accuracy. Hiding that comparison behind an optional click
   would let a viewer see only the flattering number.
3. **The moderate (2+) row is visually flagged in the table itself**
   (`tr.unreliable`, an amber warning), not only in a footnote, because a
   caveat at the bottom of the page is a caveat that gets cropped out of a
   screenshot. On a real 3+ field from the dataset, the model reports 0.02%
   moderate where the baseline reports 6.79% — the failure is visible on the
   very first field anyone tries.

---

## Testing philosophy

Two different kinds of thing are tested, and they are not the same kind.
Ordinary correctness (overlays keep their class values, tiled prediction
covers the whole image, splits contain no leaked patches, weights resolve to
the right length) is tested the normal way. But a second category —
**framing constraints** — is tested just as literally: that no score field
can appear, that the review step cannot fire without an explicit submit, that
the 2+ class is flagged in the actual rendered output and not just in a
comment. These are treated as load-bearing specification, not decoration,
because they are exactly the properties a future edit could break without
anyone noticing until a pathologist is looking at a silently-overconfident
screen.

154+ tests pass as of the last full run (`pytest -q`), spanning Phase 1
(stains, tissue, tiling, pipeline), Phase 2 (splits, losses, model, metrics,
pseudo-labels, the training loop), and the app.

---

## Reproducing this project end to end

```
# Phase 1 sanity check
python scripts/sanity_check_phase1.py

# Build the pseudo-label cache (native 40x; downsample:1 in configs/preprocessing.yaml)
python scripts/build_pseudo_labels.py --limit 900 --preview 8

# Train (unweighted baseline)
python scripts/train_phase2.py --config configs/training.yaml
python scripts/plot_training.py --run artifacts/phase2_40x
python scripts/predict_preview.py --run artifacts/phase2_40x --count 8

# Train (inverse-frequency class weights, the open experiment)
python scripts/train_phase2.py --config configs/training_weighted.yaml

# Run everything
pytest -q

# Launch the reviewer-facing demo
python -m app.server --run artifacts/phase2_40x
# then open http://127.0.0.1:8000
```

`configs/preprocessing.yaml`'s `tiling.downsample` controls magnification
(`1` = native 40×, `2` = effective 20×); `configs/training.yaml`'s
`data.cache_root` must point at a cache built with the matching setting.

---

## Where the project actually stands

**Done and defensible:** Phase 1 preprocessing (measured, not assumed, at
every stage that could silently go wrong); a working, tested Phase 2 training
pipeline with an honest, documented account of the dataset's real
limitations (no annotations → pseudo-labels; no slide IDs → an inferred,
caveated split); a model that went from unable to learn weak or moderate
staining at all, to genuinely learning weak staining at native resolution; a
complete, tested, presentable frontend that a pathologist can actually use to
compare the model against a classical control and record a judgement, with
the "assistive tool, not autonomous scorer" framing enforced by tests rather
than only stated in prose.

**Open:** the model still cannot predict the moderate (2+) class — the exact
category that decides reflex FISH testing — and the experiment designed to
tell rarity-of-class apart from resolution-limit-of-the-decode-head as the
cause is mid-run, with one epoch of encouraging but not yet conclusive
evidence. Until that's resolved, any area percentage this tool reports
under-represents 2+ and over-represents its two neighbours, and the frontend
says so on every field it analyses rather than letting that slide.

**Explicitly not started:** Phase 3 (whole-slide stitching) and Phase 4
(held-out evaluation against real pathologist review, Cohen's kappa against
`reviews.jsonl`) are gated behind Phase 2's resolution and the user's sign-off,
per the project's own stop-gate structure — nothing past this point has been
run.
