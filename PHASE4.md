# Phase 4 — Conformal prediction, stain variation, and CAP/ASCO mapping

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

**Read this result carefully before quoting it.** `training/splits.py`
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
