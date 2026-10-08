# Phase 4 — Conformal prediction, stain variation, and CAP/ASCO mapping

## Final status (2026-10-03) — read this first

Everything below the line further down is the original September write-up,
kept for history. Where it disagrees with this section, **this section is
current**: the stain estimator was fixed on 2026-10-01 (its September numbers
are superseded), a second institution (BCI) and a real whole slide (ACROBAT)
are now available, the AI pre-score (v2 multi-task model) now produces the
ASCO/CAP grade directly behind a site safety gate, and the system is
containerized and CI-verified.

| # | Objective | Status |
|---|---|---|
| 1 | Estimate stain variation across slides using adaptive stain-vector analysis | **Done** |
| 2 | Stain-shift-weighted conformal prediction under cross-institution shift | **Done** (evaluated on a real second institution) |
| 3 | Map AI predictions to ASCO/CAP HER2 score; agreement with expert ground truth | **Done** against the datasets' expert labels; local-pathologist agreement activates once reviews are recorded |
| 4 | Complete HER2 AI system with web interface and Docker | **Done and deployment-ready** (docs/DEPLOYMENT.md); hosting site is a hospital decision |

### 1. Stain variation (adaptive stain-vector analysis)

Per-image Macenko stain vectors (corrected estimator: eigenvector sign and
H/DAB order fixed 2026-10-01).

* **Across institutions and within a real slide** (`scripts/stain_variation_sites.py`,
  `artifacts/phase4/stain_variation_sites.json`; 100 images per source, 91
  tissue regions of the slide):

  | Source | H spread | DAB spread | H strength (p99) | DAB strength (p99) |
  |---|---|---|---|---|
  | HER2-IHC-40x (training site) | 5.6° | 8.4° | 0.61 | 0.32 |
  | BCI (second hospital) | 2.1° | 7.8° | 0.34 | 0.31 |
  | ACROBAT case 39 (one real whole slide, Karolinska) | 3.4° | 5.8° | 0.19 | 0.24 |

  | Between sources | H angle | DAB angle | DAB strength ratio |
  |---|---|---|---|
  | training site vs BCI | 15.9° | 8.4° | ×0.97 |
  | training site vs ACROBAT | 3.0° | 27.8° | ×0.76 |
  | BCI vs ACROBAT | 14.0° | 19.5° | ×0.79 |

  Stain directions differ between institutions by 3-5× the variation inside
  one institution or inside one slide, and counterstain strength differs
  about 3-fold. This is the cross-institution stain shift Objective 2 corrects for.
* **Within the training dataset** (`scripts/stain_variation_report.py --per-group 100`,
  `artifacts/phase4/stain_variation_fixed/`): between-group distance 0.196 vs
  within-group spread 0.138 (ratio 1.42; the September run, with the buggy
  estimator, gave 0.409 vs 0.279, ratio 1.47 — same conclusion, magnitudes
  were inflated). Groups, not slides, and confounded with HER2 score, as
  explained below.

### 2. Stain-shift-weighted conformal prediction, cross-institution

`evaluation/cross_site_conformal.py`, `scripts/conformal_cross_site.py`,
results `artifacts/conformal_cross_site/run_{a,b}.{json,md}`. Image-level
HER2 score (0/1+/2+/3+), expert labels, LAC score. Calibration: 951 held-out
training-site images; tests: the other 953 (same hospital) and 338 BCI images
(another hospital). Three thresholds: unweighted; stain-similarity (kernel)
weighted (the project's method); likelihood-ratio weighted (Tibshirani et al.
2019, domain classifier on stain features, cross-fitted, test labels unused).

Run A never saw BCI (true cross-institution test); Run B is the deployed model
(trained with BCI's training split).

| Coverage at the other hospital (target 95%) | Run A | Run B |
|---|---|---|
| unweighted | 58.9% | 82.2% |
| stain-shift weighted (kernel) | 63.6% | **91.7%** |
| likelihood-ratio weighted | 99.7% (set size 3.9 of 4) | 99.1% (set size 3.7) |
| calibrated on 25 local labelled cases (50 random splits) | 95.9% (set size 3.8) | **95.9% (set size 2.1)** |

At the same hospital every method holds its target (e.g. Run B 93.6-94.9% at
95%, 89.1-90.0% at 90%).

What this shows:

* Under real cross-institution shift, standard conformal prediction **loses
  its guarantee** (95% promised, 59-82% delivered).
* **Stain-shift weighting improves coverage** substantially for the deployed
  model (82% → 92%) but does not fully restore it: part of the shift is in how
  the institutions grade (label/concept shift), which no covariate weighting
  can correct.
* Likelihood-ratio weighting restores validity but, because the two
  institutions' stains are almost perfectly separable (domain AUC 0.999,
  effective calibration size 2), only by returning nearly every grade — the
  correct "cannot narrow this down" answer, not a useful one.
* **Calibrating on ~25 labelled cases from the new site restores the
  guarantee with informative sets** for the deployed model (2.1 grades at
  95%; at 80%, 1.3 grades and 73% single-grade answers).

In the product: the AI pre-score shows a **90% conformal prediction set**
(`app/prescore.prediction_set`, calibrated by `scripts/calibrate_prescore_sets.py`,
stored in `artifacts/v2/run_b/prescore_sets.json`), only at the site the
calibration was made for. A new hospital calibrates with its own cases (the
same ones that validate the site gate).

The September pixel-level results below were computed on a 52-patch smoke
sample with the buggy stain descriptor and are superseded by this section.

### 3. ASCO/CAP mapping and agreement with expert ground truth

The v2 model outputs the ASCO/CAP IHC category (0/1+/2+/3+) directly, with
HER2-low/ultralow from the cell-level ASCO/CAP rule, ISH guidance and
decision support (docs/PRESCORING_SYSTEM.md, docs/ISH_DECISION_SUPPORT.md),
shown only behind the site safety gate (the September "never a score" rule
was deliberately replaced by this gated design, IMPLEMENTATION_NOTES.md).
Agreement with the datasets' expert labels (`artifacts/v2/run_b/eval.json`):

| Set | n | Accuracy | QWK |
|---|---|---|---|
| HER2-IHC-40x holdout (training site) | 1,904 | 92.3% | 0.975 |
| BCI test (second hospital, training split seen) | 977 | 75.3% | 0.698 |
| Cell-level ASCO/CAP rule, holdout | — | 72.0% | 0.844 |

At a hospital never seen in training (Run A on BCI) accuracy was 48%: hence
the safety gate (pre-score withheld until locally validated). Agreement with
this project's own pathologists uses the Pathologist review tab
(`artifacts/reviews.jsonl`, `scripts/evaluate_cap_agreement.py`); it has no
real reviews yet.

### 4. Complete system, web interface, Docker

Web portal (accounts and admin console, field analysis, whole slides with
ink and control-core exclusion and per-slide control calibration (tumour is not segmented, docs/WHOLE_SLIDE.md), AI pre-score with prediction sets, ISH decision support and
explanations, pathologist review records, PDF reports); `Dockerfile`
(multi-stage: builds the portal, non-root, health check) and
`docker-compose.yml`; `/api/health`; `scripts/package_models.sh` (model bundle
with SHA-256 manifest); docs/DEPLOYMENT.md. CI builds the image from a clean
checkout and checks that the server and every dependency load inside it
(`.github/workflows/tests.yml`, job `docker`). Two defects found and fixed on
2026-10-03: the image omitted `wsi/` (the server would not start) and
`requirements.txt` omitted OpenSlide.

Still outside this project's control: real pathologist reviews, and the
Kottayam slides.

---

## Original write-up (2026-09, superseded where it conflicts with the section above)

Status: **software complete and runnable for everything that does not
require data this project does not have.** One objective — evaluating
agreement with *expert* ground truth — is built, tested, and wired to a real
data source (`artifacts/reviews.jsonl`), but has zero real rows to evaluate
until a pathologist actually uses the viewer. That is stated plainly below,
not hidden behind a metric.

This phase answers the four objectives from the project review deck. Read
"Where each objective actually stands" before reading any number below it.

---

## What was built

| Component | File |
|---|---|
| Stain-shift descriptor + kernel weighting | `evaluation/stain_shift.py` |
| Cross-group stain variation report | `evaluation/stain_variation.py` |
| Pixel-level conformal prediction, stain-shift-weighted | `evaluation/conformal.py` |
| One-time split of the reserved holdout set | `evaluation/calibration_split.py` |
| Offline ASCO/CAP mapping + agreement statistics | `evaluation/cap_mapping.py` |
| Stain variation report over the real dataset | `scripts/stain_variation_report.py` |
| Conformal calibration (spends the holdout, once) | `scripts/calibrate_conformal.py` |
| Conformal evaluation (miscoverage/ambiguity/accuracy curves) | `scripts/evaluate_conformal.py` |
| CAP agreement vs. recorded pathologist reviews | `scripts/evaluate_cap_agreement.py` |
| PDF report export | `app/report.py`, wired into `app/server.py`'s `/api/report` |
| Containerized viewer | `Dockerfile`, `docker-compose.yml`, `.dockerignore` |

Tests: `tests/test_stain_shift.py`, `test_stain_variation.py`,
`test_conformal.py`, `test_calibration_split.py`, `test_cap_mapping.py`,
`test_evaluate_cap_agreement.py`, `test_report.py`, plus additions to
`test_app.py`. 244 tests pass, Phases 1–2 included.

---

## Where each objective actually stands

### 1. Estimate stain variation across slides using adaptive stain-vector analysis

> **Stale numbers (2026-10-01).** The variation figures and the conformal
> stain-shift weights below were computed with a `estimate_macenko_stain_matrix`
> that had two bugs, both fixed while building the cross-site BCI test (see
> `docs/CROSS_SITE_STAIN_NORMALIZATION.md`): the principal eigenvector's sign
> was never oriented, so on most real patches the haematoxylin and DAB vectors
> collapsed onto the same direction (cosine ~1.0 on 19 of 24 sampled patches),
> and the H/DAB row order was inverted. The descriptor was therefore mostly
> measuring noise in a near-degenerate estimate. Re-run
> `scripts/stain_variation_report.py` (and conformal calibration, if the
> weighted results are to be quoted) before citing these numbers again.

**Done, with the same substitution every other Phase 4 result makes
explicit.** `preprocessing/stains.py` already estimated a Macenko stain
matrix per patch; `evaluation/stain_variation.py` is the piece that was
missing — it aggregates that estimate across the dataset's 8 provenance
groups and reports whether the between-group spread exceeds ordinary
within-group noise (`variation_exceeds_noise` in the JSON report).

**"Groups", not slides.** HER2_IHC_40X carries no slide identifiers (see
`training/splits.py`). Every report this produces says "provenance group"
explicitly and never upgrades that to "slide" — run
`scripts/stain_variation_report.py` to reproduce it.

**Result** (25 patches sampled per group, all 8 groups): between-group mean
distance 0.4230 vs. within-group mean spread 0.2802 —
`variation_exceeds_noise: true`. `artifacts/phase4/stain_variation.json` /
`.png`.

**Larger sample** (100 patches per group, 800 in all, same seed): between-group
mean distance 0.4087 vs. within-group mean spread 0.2788,
`variation_exceeds_noise: true`. The ratio of the two barely moves, 1.51 at 25
per group and 1.47 at 100, so the larger sample confirms the smaller one and
does not strengthen it. `python scripts/stain_variation_report.py --per-group
100 --out artifacts/phase4/stain_variation_100.json` writes it (`--out` is a
directory, hence the directory called `stain_variation_100.json` holding the
report). The report was first produced on 2026-09-17 but not written up; it was
re-run on 2026-09-22 and came out byte-identical.

**Read this result carefully before quoting it.** The confound below applies
to both sample sizes equally, and a larger sample does not weaken it. `training/splits.py`
already establishes that these 8 groups are confounded with HER2 score
(`her2-3+-score` groups are, by definition, more heavily DAB-stained than
`her2-0-score` groups). A 6-dimensional stain descriptor built from
haematoxylin and DAB directions will pick up exactly that confound: what
this measures is at least partly "different score categories have different
staining intensity," which is a real and expected property of the classes,
not evidence of cross-scanner or cross-institution stain variation. Reading
it as the latter — which is what Objective 2's weighting is meant to
correct for — would overclaim. It is genuine evidence that the stain
descriptor is sensitive enough to detect real variation of *some* kind; only
real multi-institution data can say whether that kind is the shift Objective
2 cares about.

### 2. Stain-shift-weighted conformal prediction for cross-institution uncertainty

**Done, and this is the phase's real engineering.** `evaluation/conformal.py`
generalizes the base paper's binary, image-level inductive conformal
prediction (hinge nonconformity score, per-class calibration quantile) to our
5-class, pixel-level segmentation output, and adds weighted conformal
prediction (Tibshirani et al., 2019) using a Gaussian kernel over the
6-dimensional stain descriptor as the covariate-shift weight.

**What it is calibrated against.** There are no pathologist pixel
annotations anywhere in this project. Calibration is against the DAB
optical-density pseudo-labels — the same substitution that governs every
other Phase 2 metric. A prediction set that achieves its claimed coverage
here has been shown well-calibrated against the rule the model was trained
to imitate, not against clinical truth. See
`evaluation.conformal.PSEUDO_LABEL_CALIBRATION_CAVEAT`.

**What data it spends.** `training/splits.py` reserves a held-out set and
says explicitly it is "Phase 4's to spend, once." This is that spend:
`evaluation/calibration_split.py` splits `holdout` itself into a calibration
half and a test half — never touching `fit` or `val` — via
`scripts/calibrate_conformal.py` and `scripts/evaluate_conformal.py`.

**What the weighting can demonstrate today.** HER2_IHC_40X is single-source
(`configs/preprocessing.yaml`'s `normalization: none`, precisely because
there is no inter-scanner variation here to correct). The stain-shift
weighting mechanism is real, unit-tested against deliberately-constructed
synthetic multi-source data (`tests/test_conformal.py`'s
`test_stain_shift_weighting_favours_nearby_calibration_evidence`), and on
this single-source dataset should come out close to identical to the
unweighted baseline — which the results below confirm. That is the honest
result of running a cross-institution correction on single-institution data,
not a failure of the method.

**Results, `artifacts/phase2_40x/` (40x run), a smoke-scale calibration/test
split** (`--max-patches 40` on each side, stratified across all four
classes; 157 calibration tiles, 52 test tiles, 10,595,420 test pixels total.
A full run over all ~1,900 holdout patches is unrun — CPU-only, and at this
per-tile cost (~1s/tile for inference alone) that is a multi-hour job, the
same order of cost `configs/training.yaml` already states for a full Phase 2
training run):

| alpha | miscoverage (unweighted) | ambiguity (unweighted) | accuracy (unweighted) | miscoverage (weighted) | ambiguity (weighted) | accuracy (weighted) |
|---|---|---|---|---|---|---|
| 0.01 | 0.009 | 0.642 | 1.000 | 0.009 | 0.621 | 1.000 |
| 0.05 | 0.033 | 0.479 | 0.997 | 0.035 | 0.467 | 0.997 |
| 0.10 | 0.069 | 0.429 | 0.993 | 0.075 | 0.418 | 0.992 |
| 0.15 | 0.106 | 0.388 | 0.979 | 0.118 | 0.359 | 0.961 |
| 0.20 | 0.151 | 0.307 | 0.925 | 0.168 | 0.277 | 0.907 |
| 0.25 | 0.204 | 0.235 | 0.876 | 0.224 | 0.240 | 0.873 |
| 0.30 | 0.260 | 0.248 | 0.864 | 0.278 | 0.272 | 0.870 |
| 0.40 | 0.368 | 0.342 | 0.864 | 0.395 | 0.375 | 0.871 |
| 0.50 | 0.480 | 0.442 | 0.858 | 0.501 | 0.471 | 0.867 |

Two things worth reading off this table directly:

* **Miscoverage tracks alpha closely at every row** (0.033 at alpha=0.05,
  0.069 at alpha=0.10, ...) — the finite-sample coverage guarantee holding
  on real held-out data, not just in the unit tests
  (`tests/test_conformal.py`'s Monte Carlo check). This is the same
  validation the base paper's own Fig. 5(a) performs.
* **Ambiguity and accuracy both trace the same U-shape the base paper
  reports** (Section IV.B/C): ambiguity is highest at very low and very high
  alpha and lowest around alpha≈0.25-0.30; accuracy is highest at the
  extremes and lowest in the middle. The mechanism is identical to theirs:
  at low alpha most pixels get a wide, safe prediction set; at high alpha
  most get a narrow, confident one; the middle forces singleton predictions
  the model is least sure of.
* **Weighted and unweighted are close at every row**, exactly as
  documented above: HER2_IHC_40X has no real cross-institution stain shift
  for the weighting to correct, so there is nothing here for it to visibly
  improve. The mechanism itself is validated separately, on synthetic
  shifted data, in `tests/test_conformal.py`.

Patch-level accuracy was 1.000 at every alpha in this run — read that as a
**52-patch smoke sample**, not as a claim; it is not run at a scale that
supports a real number yet.

Full per-alpha numbers: `artifacts/phase2_40x/conformal_eval.csv`. Curves:
`artifacts/phase2_40x/conformal_curves.png`.

### 3. Map AI predictions to CAP/ASCO HER2 score and evaluate agreement with expert ground truth

**The mapping is done. The live viewer still does not, and must not, expose
it.** `evaluation/cap_mapping.py` implements the ASCO/CAP 2018 thresholds
(Wolff et al.) over the model's area percentages. It is deliberately **not**
imported anywhere under `app/` — this project's one enforced rule (see
IMPLEMENTATION_NOTES.md, and `tests/test_app.py`) is that no live API
response ever carries a field named `score`, `her2_score`, `verdict` or
`diagnosis`. A `cap_score` field in the live JSON would be that same rule
broken under a different name. The mapping is an offline, evaluation-time
tool, run by a script and read by a person — never a field a pathologist's
browser receives while looking at a slide.

**Agreement evaluation is real, tested, and wired to a real data source —
with zero rows to evaluate today.** `scripts/evaluate_cap_agreement.py`
reads `artifacts/reviews.jsonl` (the file `/api/review` appends to every
time a pathologist confirms a score in the viewer — see app/README.md's
"Reviews", written *before* this phase existed, already naming this as
Phase 4's job) and computes exact agreement, within-one-category agreement,
and quadratic-weighted Cohen's kappa against the model's CAP-mapped
category. Run today:

```
$ python scripts/evaluate_cap_agreement.py
No reviews file at artifacts/reviews.jsonl yet -- nothing to evaluate.
This is expected until a pathologist has used the viewer; see app/README.md's 'Reviews' section.
```

That is the honest, current state: no pathologist has used the viewer yet,
so there is no expert ground truth to agree or disagree with. The pipeline
is complete and tested (`tests/test_evaluate_cap_agreement.py` exercises it
end-to-end against a synthetic reviews file) and activates automatically the
first time a real review is recorded.

**The denominator problem does not go away.** ASCO/CAP scoring is defined on
percentage of *tumour cells*; every measurement in this project is
percentage of *tissue area*, which includes stroma. See
`evaluation.cap_mapping.DENOMINATOR_CAVEAT` — it travels with every result
this module produces, including a future real agreement number.

### 4. Build and deploy a complete HER2 AI system with a web interface, Docker, and report generation

**Web interface:** already existed (`app/server.py`, standard library only,
no framework, no CDN). Unchanged in substance this phase.

**Report generation:** new. `app/report.py` renders exactly the payload
`/api/analyze` returns — the same images, the same measurements, the same
caveats — to a PDF, via `POST /api/report`. It carries the same "never a
score" guarantee as the live API, checked directly in
`tests/test_report.py`, because it is built from that exact dict.

**Docker:** new. `Dockerfile` + `docker-compose.yml` package the viewer.
Two things worth knowing before running it:

* `torch` is deliberately not in `requirements.txt` (needs the CPU wheel
  index, not plain PyPI) — the Dockerfile installs it explicitly from
  `download.pytorch.org/whl/cpu`, pinned to the exact version this project
  runs on. Missing this is the single most likely way a from-scratch
  container build would silently produce a broken image.
* `docker-compose.yml` publishes the viewer on `127.0.0.1` on the **host**
  only, matching `app/server.py`'s own documented stance: this is a local
  demonstration and review aid, with no authentication and no transport
  security, not a service to expose more broadly. Containerizing it changes
  how it is launched, not what it is safe to expose it to.

```
docker compose up --build
```

**Verification status (2026-09-17):** still not run. No Docker is available
on this machine (`docker`/`docker compose` not on `PATH`, and there is no
`winget` or other package manager to install it non-interactively either --
Docker Desktop's own installer needs interactive administrator elevation,
which this environment cannot grant itself). Per
`tasks/person2_evaluation_infra.md` Task 2's own fallback: "if you don't
have Docker either, say so plainly ... rather than skipping this silently."
The `Dockerfile`/`docker-compose.yml` themselves are unchanged and were not
re-reviewed beyond what this document already describes -- whoever picks
this up next with real Docker access should treat it as still fully open,
not "probably fine."

---

## What is still open

* **A full-scale conformal calibration and evaluation run**, over the whole
  reserved holdout set rather than a 40-patch smoke sample. Software-ready;
  CPU-only hardware makes this a multi-hour batch job, the same category of
  cost Phase 2's own full training run already carries.
* **Real pathologist reviews.** Nothing here can manufacture expert ground
  truth; it can only be ready the moment it exists.
* **The Kottayam slides**, still not digitized. Every caveat inherited from
  Phase 1–2 about HER2_IHC_40X being a substitute, not the target data,
  applies identically here.
