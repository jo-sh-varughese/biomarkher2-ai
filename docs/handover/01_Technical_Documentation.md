---
title: Technical Documentation
subtitle: BioMarkHER2, HER2 IHC pre-scoring and review portal
doc_id: BMH-SDC-01
---

# Technical Documentation

| | |
|---|---|
| System | BioMarkHER2: AI-assisted HER2 immunohistochemistry (IHC) pre-scoring and review portal |
| Release | `sdc-2026.11.11` (Docker image `biomarkher2:sdc-2026.11.11`) |
| Application version | 0.2.0 (server), 2.0.0 (web portal) |
| Prepared for | State Data Centre (SDC) and K-DISC, project "HER2 Biomarker" |
| Prepared by | BioMarkHER2 project team |
| Date | 11 November 2026 |

## 1. Purpose and intended use

BioMarkHER2 helps a pathologist score HER2 IHC in breast cancer on the ASCO/CAP 0 / 1+ / 2+ / 3+ scale.
For a field image or a whole scanned slide it shows:

* an **AI pre-score** (suggested grade with probabilities and a 90% prediction set), shown only at a site where it has been validated;
* **cell-level ASCO/CAP evidence**: each detected cell classified by membrane completeness and intensity, and the percentage of cells in each category;
* **ISH decision support** following ASCO/CAP 2018 (affirmed 2023), with the reasons for and against;
* **explanations**: AI evidence heatmap, per-region pre-scores, cell membrane map, stain-intensity map;
* a **quality gate** that refuses to grade an unusable image (blank, blurred, wrong stain, too few cells);
* a **pathologist review record** (draft → preliminary → final, with amendments) and a PDF report.

**The pathologist signs every score.** The system is a pre-scoring and decision-support aid. It is not a
certified medical device and has not been validated for autonomous diagnostic use. Section 9 lists the known
limitations; they must be read before clinical use.

## 2. System architecture

<figure>
<svg viewBox="0 0 900 360" xmlns="http://www.w3.org/2000/svg" font-family="Segoe UI, Arial, sans-serif" font-size="13">
  <defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#555"/></marker></defs>
  <rect x="10" y="140" width="130" height="70" rx="8" fill="#eef2ff" stroke="#6366f1"/>
  <text x="75" y="170" text-anchor="middle" font-weight="600">Pathologist</text>
  <text x="75" y="190" text-anchor="middle">browser (VPN)</text>
  <line x1="140" y1="175" x2="190" y2="175" stroke="#555" marker-end="url(#a)"/>
  <text x="165" y="165" text-anchor="middle" font-size="11">HTTPS 443</text>
  <rect x="195" y="140" width="120" height="70" rx="8" fill="#f1f5f9" stroke="#64748b"/>
  <text x="255" y="170" text-anchor="middle" font-weight="600">Caddy proxy</text>
  <text x="255" y="190" text-anchor="middle">TLS, 80→443</text>
  <line x1="315" y1="175" x2="365" y2="175" stroke="#555" marker-end="url(#a)"/>
  <text x="340" y="165" text-anchor="middle" font-size="11">:8000</text>
  <rect x="370" y="20" width="510" height="320" rx="10" fill="#fff" stroke="#0f766e" stroke-width="1.5"/>
  <text x="385" y="42" font-weight="700" fill="#0f766e">app container (Python 3.11, CPU only, uid 10001)</text>
  <rect x="385" y="55" width="230" height="52" rx="6" fill="#f0fdfa" stroke="#14b8a6"/>
  <text x="500" y="77" text-anchor="middle" font-weight="600">Web portal (React, static)</text>
  <text x="500" y="95" text-anchor="middle" font-size="11">served from ui/dist</text>
  <rect x="385" y="117" width="230" height="52" rx="6" fill="#f0fdfa" stroke="#14b8a6"/>
  <text x="500" y="139" text-anchor="middle" font-weight="600">HTTP API (app/server.py)</text>
  <text x="500" y="157" text-anchor="middle" font-size="11">accounts, roles, CSRF, audit</text>
  <rect x="385" y="179" width="230" height="70" rx="6" fill="#f0fdfa" stroke="#14b8a6"/>
  <text x="500" y="199" text-anchor="middle" font-weight="600">Analysis pipeline</text>
  <text x="500" y="217" text-anchor="middle" font-size="11">quality gate → cells → stain map</text>
  <text x="500" y="233" text-anchor="middle" font-size="11">→ AI pre-score → site gate → ISH</text>
  <rect x="385" y="259" width="230" height="66" rx="6" fill="#f0fdfa" stroke="#14b8a6"/>
  <text x="500" y="281" text-anchor="middle" font-weight="600">Whole slides (wsi/)</text>
  <text x="500" y="299" text-anchor="middle" font-size="11">OpenSlide, ink/control exclusion,</text>
  <text x="500" y="315" text-anchor="middle" font-size="11">40 fields, attention pooling</text>
  <rect x="635" y="55" width="230" height="114" rx="6" fill="#fff7ed" stroke="#f59e0b"/>
  <text x="750" y="77" text-anchor="middle" font-weight="600">Models (mounted, read)</text>
  <text x="750" y="99" text-anchor="middle" font-size="11">Stain map: ResNet18-UNet</text>
  <text x="750" y="117" text-anchor="middle" font-size="11">AI pre-score: ResNet-50 multi-task</text>
  <text x="750" y="135" text-anchor="middle" font-size="11">conformal calibrations</text>
  <text x="750" y="153" text-anchor="middle" font-size="11">artifacts/…/best.pt</text>
  <rect x="635" y="179" width="230" height="146" rx="6" fill="#fef2f2" stroke="#ef4444"/>
  <text x="750" y="201" text-anchor="middle" font-weight="600">Records (mounted, written)</text>
  <text x="750" y="223" text-anchor="middle" font-size="11">biomark.db: accounts, audit</text>
  <text x="750" y="241" text-anchor="middle" font-size="11">cases.sqlite3: case database</text>
  <text x="750" y="259" text-anchor="middle" font-size="11">reviews.jsonl, annotations.jsonl</text>
  <text x="750" y="277" text-anchor="middle" font-size="11">prescore_shadow_log.jsonl</text>
  <text x="750" y="295" text-anchor="middle" font-size="11">learning/ (cases, versions)</text>
  <text x="750" y="313" text-anchor="middle" font-size="11">slides/ (WSI files)</text>
</svg>
<figcaption>Figure 1. Deployment architecture at the SDC. Everything runs on one VM; nothing leaves it at run time.</figcaption>
</figure>

* **One application container** serves the portal, the API, both models and PDF generation. There is no separate
  database server, message queue or external service. The server is Python's standard-library HTTP server
  (threaded); the web portal is a static React build served by the same process.
* **One proxy container** (Caddy) terminates HTTPS and redirects HTTP. The application port (8000) is bound to
  `127.0.0.1` on the VM and is never exposed to the network.
* **Persistent state** is two host directories: `artifacts/` (models, databases, logs) and `slides/`
  (whole-slide files). Back up `artifacts/` (Deployment Guide §8).
* **No outbound network access at run time.** Model weights are loaded from disk; nothing is downloaded,
  and no telemetry is sent.

### 2.1 Request flow for one field

1. The browser sends `POST /api/analyze` with the image (PNG/JPEG/TIFF, up to 24 MB, at most 64 megapixels).
2. `app/image_io.py` decodes it safely (EXIF rotation, 16-bit, CMYK, transparency, multi-page TIFF).
3. **Field-quality gate** (`app/field_quality.py`): 16 checks (focus, stain type, tissue, cell count, ink, …).
   A blocking failure ends the analysis as **Not assessable**: no AI pre-score, no grade, no ISH suggestion.
4. **Cell evidence** (`app/cells.py`): nuclei → cells → membrane ring → per-cell completeness and intensity →
   ASCO/CAP category per cell → field category by the 10% rule.
5. **Stain map** (`app/analysis.py`): ResNet18-UNet pixel classes (negative / weak / moderate / strong) and
   a classical DAB-threshold baseline, side by side, with conformal uncertainty.
6. **AI pre-score** (`app/prescore.py`): ResNet-50 multi-task network over 512 px tiles, gated-attention
   pooling to one grade, Grad-CAM evidence, 90% conformal prediction set.
7. **Site safety gate** (`evaluation/safety_gate.py`): shows the pre-score only if this site has a valid local
   validation record. Otherwise it is withheld and written to the shadow log (Section 8).
8. **Guidance and decision support** (`app/guidance.py`, `app/decision.py`, `app/explain.py`): ISH
   required / recommended / not indicated, with evidence for and against, cut-off proximity and stability.
9. The result is stored in the case database and the learning store, and returned to the browser.
   The pathologist reviews it and records a score (`POST /api/review`); the score is never pre-filled.

### 2.2 Whole slides

`wsi/` reads slides with OpenSlide at physical resolution (µm/px), finds tissue, excludes blue ink, mounting
film and on-slide control cores, selects up to 40 fields of 1024 px at 0.24 µm/px, and runs the field
pipeline on each. The slide pre-score is attention-pooled over every analysed tile; cell percentages are pooled
over all measured cells; the highest-weighted fields are shown as hotspots. Slides scanned coarser than
0.5 µm/px (below about 20×) never receive a pre-score. Supported formats: `.svs`, `.tif/.tiff`, `.ndpi`,
`.mrxs`, `.scn`, `.vms`, `.vmu`, `.bif`, `.svslide`, plus large `.png/.jpg` images. Uploads up to 8 GB.

## 3. Models

The release contains two trained neural networks and one calibrated rule engine.

### 3.1 AI pre-score model

| Item | Value |
|---|---|
| Name / version | `run_b`, epoch 11 (model version `v0` in the learning registry) |
| File | `artifacts/v2/run_b/best.pt` (139.6 MB), SHA-256 `5254ac20…61a2d0f5` |
| Calibration file | `artifacts/v2/run_b/prescore_sets.json` (conformal prediction sets, 951 cases) |
| Architecture | Multi-task U-Net (`models/multitask.py`): ResNet-50 encoder, U-Net decoder (5-class stain segmentation, auxiliary), gated-attention multiple-instance pooling over 512 px tiles, 4-class score head (0 / 1+ / 2+ / 3+) |
| Input | RGB + DAB optical density (4 channels), 512 × 512 px tiles at ≈0.24 µm/px (40×) |
| Encoder initialisation | Pathology self-supervised ResNet-50 weights (Lunit, Barlow Twins; Kang et al., CVPR 2023) |
| Training data | HER2-IHC-40x (7,729 fit patches) + BCI training images (11,235 samples in total) |
| Loss | Cross-entropy on grade (label smoothing 0.05) + 0.5 × segmentation loss on pseudo-labels + 0.2 × ordinal loss |
| Augmentation | Stain-vector rotation ±8°, haematoxylin ×0.7–1.4, DAB ×0.75–1.3, zoom 0.8–1.25, blur, noise, brightness/contrast |
| Optimiser | AdamW, lr 3·10⁻⁴ (encoder ×0.3), weight decay 10⁻⁴, 5% warm-up, gradient clip 1.0 |
| Training run | 16 epochs, 41.6 min on one rented GPU (bfloat16); model selected on validation QWK (epoch 11) |
| Configuration | `configs/v2_run_b.yaml`; resolved copy `artifacts/v2/run_b/resolved_config.json` |
| Inference | CPU, float32; about 20–30 s per field on 4 cores |

### 3.2 Stain-map model

| Item | Value |
|---|---|
| Name / version | `phase2_unet_8epochs`, epoch 6 of 8 |
| File | `artifacts/phase2_unet_8epochs/best.pt`, SHA-256 `078d1497…7fabe86eb`; conformal calibration `conformal_calibration.npz` |
| Architecture | U-Net with ResNet18 encoder (`models/unet_seg.py`), 4-channel input (RGB + DAB optical density) |
| Output | Per-pixel class: background, negative, weak (1+), moderate (2+), strong (3+) |
| Training targets | DAB optical-density threshold pseudo-labels (no pixel annotations exist); not pathologist annotations |
| Loss | Cross-entropy + 0.5 × Dice + focal (γ = 2) |
| Configuration | `configs/training.yaml`, `configs/training_unet_8epochs.yaml`, `configs/preprocessing.yaml` |
| Role | The explainable intensity map and the area percentages beside the classical baseline. It does not produce the grade. |

### 3.3 Cell-level ASCO/CAP engine (no neural network)

`app/cells.py` with parameters in `configs/cell_params.json`. Nuclei come from the haematoxylin channel
(colour deconvolution, watershed split). Each nucleus is grown to its cell territory, and the outer ring is read in
24 angular sectors for DAB completeness and intensity. Cut points (faint 0.25, strong 0.80 OD; complete ≥ 50% of
sectors) were calibrated on 80 training patches and measured once on 100 held-out patches.

### 3.4 Model files and checksums

`artifacts/MODELS.sha256` lists every model file; `install.sh` and `smoke_test.sh` verify it.

| File | SHA-256 |
|---|---|
| `artifacts/phase2_unet_8epochs/best.pt` | `078d1497864ba947a31a6bda47afdc76184c30c2269a1e82dc0e30a7fabe86eb` |
| `artifacts/phase2_unet_8epochs/conformal_calibration.npz` | `092c18bcd3c72d8de71e6df098cf907a16727428874215bc33209dae62910b76` |
| `artifacts/phase2_unet_8epochs/conformal_calibration_ids.json` | `6135371d7189a9583e1097a826ca056a624cd4ed498d79cbab4d0912e8d42bea` |
| `artifacts/v2/run_b/best.pt` | `5254ac20146f935e223d9a8e3ddfec3449b4610ae52fb5b21e2c1fe261a2d0f5` |
| `artifacts/v2/run_b/prescore_sets.json` | `67785cc795b1ac0522688a1f35af357e6d55b34ec37810b92d606792b8f1ba7c` |

## 4. Development methodology

### 4.1 Data

| Dataset | Use | Notes |
|---|---|---|
| HER2-IHC-40x (≈11,000 patches of 1024 × 1024 px, one HER2 score per patch, 40×) | Training site: training, validation, held-out test | Public; no slide identifiers, so the held-out split follows the dataset authors' own train/test assignment |
| BCI (Liu et al., CVPR-W 2022; Hamamatsu, ≈20×) | A second institution: training (pre-score model) and cross-site testing | Case-level scores from pathology reports |
| HER2match (Zenodo 10.5281/zenodo.15797050, 3DHistech, 0.25 µm/px) | Whole-slide cross-scanner tests; fine-tuning experiments (not adopted) | One score per slide; CC BY-NC-SA 4.0 |
| ACROBAT case 39 (Karolinska, CC BY 4.0, 10×) | Whole-slide viewer, exclusions and safety rules | Too coarse to score; correctly receives no pre-score |
| K-DISC Medprime slides 1–4 (0.286 µm/px, 40×) | First slides from the deployment programme | No pathologist scores provided; see §6.4 |

No dataset is included in the handover (only the trained models are required). Evaluation outputs (metrics and
confusion matrices) are in `02_Models/evaluation/`.

### 4.2 Preprocessing

`preprocessing/`: Ruifrok–Johnston colour deconvolution (haematoxylin, eosin, DAB), optical-density tissue
detection, tiling (512 px), and the classical DAB-threshold baseline. All settings are in
`configs/preprocessing.yaml`, a plain YAML loaded into typed dataclasses that reject unknown keys.

### 4.3 Annotation

No pixel-level or cell-level pathologist annotations were available. Labels used:

* **grades**: one HER2 score per patch (HER2-IHC-40x) or per case (BCI, HER2match), as published;
* **pixel targets** for the segmentation heads: DAB optical-density threshold pseudo-labels
  (`training/pseudo_labels.py`, `scripts/build_pseudo_labels.py`);
* **in the deployed system**: pathologists' signed reviews and region annotations become labels for local
  learning (Section 8.3).

### 4.4 Training

* Stain map: `scripts/train_phase2.py --config configs/training_unet_8epochs.yaml` (CPU).
* AI pre-score: `scripts/train_v2.py --config configs/v2_run_b.yaml` (one GPU; pod scripts in `scripts/pod/`;
  plan, budget and protocol in `docs/V2_TRAINING_PLAN.md`). Targets and evaluation protocol were fixed before
  any GPU run.
* Splits: `configs/splits/`. A fixed holdout of 1,904 HER2-IHC-40x patches was never used for training or model
  selection.

### 4.5 Validation and testing

* **Model selection** on validation splits only (per-epoch metrics in `artifacts/*/history.json`, `val_metrics_*.json`).
* **Held-out testing** once, with `scripts/eval_v2.py` (pre-score) and `scripts/evaluate_conformal.py` (stain map).
* **Cross-site testing** on BCI and HER2match (`scripts/conformal_cross_site.py`, `scripts/score_her2match_slides.py`).
* **Software tests**: 563 automated tests (`pytest`), run on every push by GitHub Actions together with a Docker
  build in which the stain-map model is loaded with networking disabled. Some tests encode safety rules: no API response may
  contain a field named `score`, `verdict` or `diagnosis`, and the pre-score is never shown at an unvalidated site.

### 4.6 Inference workflow

See §2.1 (field) and §2.2 (slide). Entry points: `app/server.py` (portal), `scripts/batch_report.py` (batch PDF
reports for a folder), `scripts/score_kdisc_slides.py` (command-line slide scoring).

## 5. Uncertainty and safety mechanisms

| Mechanism | What it does | Where |
|---|---|---|
| Site safety gate | Pre-score shown only with a local validation record for this site name: ≥100 cases, ≥90% accuracy, QWK ≥ 0.85, ≤1% off by two grades. Otherwise **shadow mode** (computed, logged, not shown) or **blocked** (unknown magnification). | `evaluation/safety_gate.py` |
| Field-quality gate | 16 checks; blocks blank, dark, noisy, greyscale, H&E, nuclear-stain, marker-ink, out-of-focus and cell-poor fields | `app/field_quality.py`, `docs/FIELD_QUALITY.md` |
| Conformal prediction | 90% prediction set for the pre-score; pixel-level conformal sets for the stain map | `evaluation/conformal.py` |
| Magnification rule | Slides coarser than 0.5 µm/px get no pre-score and are flagged | `wsi/analysis.py` |
| Review rules | Final score refused on inadequate tissue, unacceptable control, non-breast site, or no invasive tumour; final records are never edited, only amended | `app/review_record.py` |
| No automation bias | The review score is never pre-filled from the AI | `ui/src/pages/Review.jsx` |

## 6. Performance evaluation

### 6.1 AI pre-score, training site (held-out)

1,904 reserved HER2-IHC-40x patches, never used for training or selection.

| Metric | Value |
|---|---|
| Accuracy | **92.3%** |
| Balanced accuracy | 89.5% |
| Macro-F1 | 0.888 |
| Quadratic weighted kappa (QWK) | **0.975** |
| Within one grade | 99.8% |
| Off by two or more grades | 0.21% (4 of 1,904) |

Confusion matrix (rows = reference grade, columns = AI pre-score):

| Reference \ AI | 0 | 1+ | 2+ | 3+ | Recall |
|---|---|---|---|---|---|
| **0** (658) | **601** | 56 | 0 | 1 | 91.3% |
| **1+** (349) | 41 | **293** | 15 | 0 | 84.0% |
| **2+** (124) | 2 | 12 | **105** | 5 | 84.7% |
| **3+** (773) | 0 | 1 | 13 | **759** | 98.2% |

### 6.2 AI pre-score at other sites

| Test | n | Accuracy | QWK | Comment |
|---|---|---|---|---|
| BCI test (a site in Run B's training data) | 977 | 75.3% | 0.698 | Below the 90% target |
| BCI test, model never trained on BCI (Run A) | 977 | 48–55% | ≈0.31 | **An unseen hospital.** The most confident answers were often the wrong ones. This result is why the site gate exists. |
| HER2match whole slides (unseen scanner), held-out tumour tiles | 1,556 tiles | 56.7% | n/a | 0 and 3+ correct; held-out 1+ and 2+ slides called 0. Stain normalisation did not help; slide-label fine-tuning made results worse and was not adopted. |

BCI test confusion matrix (Run B, raw images):

| Reference \ AI | 0 | 1+ | 2+ | 3+ |
|---|---|---|---|---|
| **0** (38) | **32** | 1 | 2 | 3 |
| **1+** (235) | 9 | **152** | 57 | 17 |
| **2+** (446) | 17 | 58 | **327** | 44 |
| **3+** (258) | 2 | 10 | 21 | **225** |

**Conclusion:** the pre-score is accurate at its training site and not reliable at a new hospital until validated
there. This is the reason for shadow mode at the SDC deployment (Section 8.1).

### 6.3 Cell-level ASCO/CAP evidence

100 held-out patches (cut points fitted on 80 training patches):

| Metric | Value |
|---|---|
| Accuracy | 72.0% |
| QWK | 0.844 |
| Recall 0 / 1+ / 2+ / 3+ | 64% / 52% / 76% / 96% |

| Reference \ Cells | 0 | 1+ | 2+ | 3+ |
|---|---|---|---|---|
| **0** | **16** | 8 | 1 | 0 |
| **1+** | 3 | **13** | 9 | 0 |
| **2+** | 0 | 0 | **19** | 6 |
| **3+** | 1 | 0 | 0 | **24** |

Weakest at 0 vs 1+ (HER2-low status). Tumour cells are not separated from stroma or normal epithelium.

### 6.4 Stain-map model (validation, pseudo-label targets)

| Class | IoU | Dice | Precision | Recall |
|---|---|---|---|---|
| Background | 0.896 | 0.945 | 0.940 | 0.950 |
| Negative | 0.898 | 0.946 | 0.954 | 0.938 |
| Weak (1+) | 0.778 | 0.875 | 0.849 | 0.903 |
| Moderate (2+) | **0.657** | 0.793 | 0.773 | 0.814 |
| Strong (3+) | 0.912 | 0.954 | 0.961 | 0.947 |
| **Tissue mean IoU** | **0.811** | | Pixel accuracy | 0.938 |

These figures measure agreement with threshold-derived pseudo-labels, not clinical accuracy. Validation
patches may share slides with training patches (the dataset has no slide IDs), so they are optimistic.

### 6.5 K-DISC slides (deployment site, first look)

Four Medprime Technologies whole slides received from K-DISC (0.286 µm/px, Aperio TIFF), scored on 31 October 2026:

| Slide | Cells measured | Cell evidence | % cells 3+ | ISH guidance | Note |
|---|---|---|---|---|---|
| 1 | 1,861 | 3+ | 96.0% | Not indicated by IHC | |
| 2 | 1,645 | 3+ | 94.5% | Not indicated by IHC | |
| 3 | 57 | **Not assessable** | n/a | n/a | Heavy marker ink; the only stained section is out of focus. Needs a re-scan. |
| 4 | 2,784 | 3+ | 99.4% | Not indicated by IHC | |

**No pathologist scores were provided for these slides, so accuracy at K-DISC cannot yet be stated.** All
readable slides are strongly positive and do not test the clinically difficult 0 / 1+ / 2+ boundaries.
Whole-slide analysis took 4–11 minutes per slide on CPU.

Re-run of slide 1 on this release during the deployment rehearsal: IHC 3+ by cell evidence, 2,485 cells measured,
93.2% of cells 3+, ISH not indicated by IHC, one on-slide control core found and excluded, AI pre-score withheld
(shadow mode). The call is unchanged; the cell counts differ from 31 October because the field-selection code changed
between the two runs.

## 7. Technology stack

| Layer | Technology | Version |
|---|---|---|
| Language (server) | Python | 3.11 (image `python:3.11-slim`) |
| Deep learning | PyTorch, torchvision (CPU builds) | 2.13.0, 0.28.0 |
| Image analysis | NumPy, SciPy, scikit-image, scikit-learn, Pillow, tifffile | 2.4.6, 1.17.1, 0.26.0, 1.9.0, 12.3.0, 2026.3.3 |
| Whole-slide reading | OpenSlide (openslide-python + openslide-bin) | 1.4.6, 4.0.1.2 |
| PDF reports | ReportLab | 5.0.1 |
| Config | PyYAML | 6.0.3 |
| Web server | Python standard library `http.server` (threaded); no Flask/FastAPI | |
| Databases | SQLite (standard library): accounts/audit, case database | |
| Web portal | React 18, React Router 6, OpenSeadragon 4 (slide viewer), Vite 5, Tailwind CSS 3, lucide-react | see `ui/package.json`, `ui/package-lock.json` |
| Build-time only | Node.js 22 (inside the image's first build stage) | |
| Packaging | Docker (multi-stage `Dockerfile`), Docker Compose v2 | Docker 24+ |
| HTTPS | Caddy 2 (container) | `caddy:2-alpine` |
| Tests / CI | pytest 9.1.1; GitHub Actions | |

The full pinned Python list is `requirements.txt`; the full JavaScript dependency tree is `ui/package-lock.json`.
Nothing is fetched from a CDN at run time.

### 7.1 Hardware requirements

| | Minimum (pilot) | Recommended |
|---|---|---|
| CPU | 4 vCPU x86-64 | 8 vCPU |
| RAM | 8 GB | 16 GB (concurrent whole-slide work) |
| Disk | 20 GB + slides (0.3–0.7 GB each) | SSD; 100 GB holds ≈100–200 slides |
| GPU | Not used | Not used |
| OS | Linux with Docker 24+ and Compose v2 | Ubuntu 22.04 / 24.04 LTS |

Measured in the release container under a 6 GB memory cap: whole-slide analysis peaked at 1.4 GB RAM (K-DISC slide 1,
141,303 × 72,341 px) and took 4.3 min; a field takes 20–30 s; whole slides take 4–11 min (40 fields). Analysis is largely single-threaded per request; `BIOMARK_ANALYSIS_SLOTS` sets how many
analyses run at once (others queue).

## 8. Integration, APIs and operating modes

### 8.1 Site validation (shadow mode)

At the SDC the server runs with `--site-name "<hospital>"` and no validation record, so the pre-score is
**withheld** and logged to `artifacts/prescore_shadow_log.jsonl`. Everything else works. To enable the pre-score,
pathologists sign about 100 or more cases across all four grades, the shadow log is compared with their scores
(`scripts/evaluate_cap_agreement.py`), and a validation record is written (example
`configs/site_validation/her2_ihc_40x.json`). The server then starts with `--site-validation <record>`; the gate
accepts it only if it names this site and meets the thresholds. `--research-prescores` shows unvalidated scores
with a red "research mode" banner and must never be used for patient care.

### 8.2 HTTP API

All routes are under `/api`, JSON in and out, session cookie plus `X-CSRF-Token` header on every state-changing
request. Roles: administrator, pathologist, viewer.

| Area | Routes |
|---|---|
| Health | `GET /api/health` (public): `{"status","stain_model","prescore_model","slides"}` |
| Auth | `GET /api/auth/config`, `GET /api/auth/me`, `POST /api/auth/login`, `/logout`, `/setup`, `/request-access`, `/password`, `/link`, `PATCH /api/auth/profile`, `/api/auth/sessions…` |
| Fields | `GET /api/context`, `POST /api/analyze`, `POST /api/report` (PDF), `POST /api/annotations` |
| Reviews and cases | `POST /api/review`, `GET /api/reviews`, `GET /api/cases`, `GET /api/cases/{case_id}` |
| Whole slides | `GET /api/slides`, `POST /api/slides/upload?name=` (raw body, ≤ 8 GB), `GET /api/slides/{id}/info`, `/dzi`, `/dzi_files/…` (viewer tiles), `POST /api/slides/{id}/analyze`, `GET /api/slides/{id}/analysis`, `GET /api/slides/{id}/report` |
| Admin | `/api/admin/overview`, `/users…`, `/sessions…`, `/audit`, `/audit.csv`, `/settings`, `/system`, `/users.csv`, `/export/reviews.jsonl`, `/export/annotations.jsonl`, `/learning…` |

The full auth/admin route table is in `docs/ACCOUNTS_AND_ADMIN.md`. There is no integration with a laboratory
information system (LIS/HIS) or PACS in this release. Data leave the system only through the documented PDF and
CSV/JSONL exports, each of which is audited.

### 8.3 Continual learning (administrator-controlled)

Every analysed case is stored with its tile features (`artifacts/learning/`). Signed final reviews and region
annotations become labels. An administrator can train a **candidate** version of the pre-score head (about 66k
parameters, on CPU, in seconds to minutes). It becomes eligible only if it passes gates fixed in
`configs/learning.yaml`: at least 40 signed cases with at least 3 per grade, no loss on the locked reference set,
a gain of at least 2 points on local cross-validation, and no new two-grade errors. Activation and rollback are
manual and audited. Details: `docs/LEARNING.md`.

**Release note:** the locked reference file `artifacts/learning/reference_run_b.npz` is not in this release. Until
it is produced (`scripts/extract_learning_features.py --sets replay,reference`, GPU recommended), cases are
collected but candidate training is refused with "Reference features not found".

## 9. Known limitations

1. **Not validated at the deployment site.** The pre-score is validated only at its training site. At an unseen
   hospital accuracy fell to 48–55%. It stays withheld at the SDC until a local validation study is completed.
2. **HER2-low boundaries are the weakest.** 0 vs 1+ and 1+ vs 2+ are where the cell engine (recall 64% for 0, 52%
   for 1+) and the cross-site pre-score fail most; pathologists also disagree most there.
3. **Tumour is not segmented.** All detected cells count, including stroma, lymphocytes, DCIS and normal ducts.
   The pathologist confirms that the scored area is invasive tumour.
4. **Labels are coarse.** Training used patch- or case-level scores and threshold pseudo-labels, not cell
   annotations. Stain-map metrics measure agreement with pseudo-labels only.
5. **No K-DISC ground truth.** The four K-DISC slides have no pathologist scores; three are strongly 3+ and one is
   unreadable.
6. **Brown pigment** (melanin, haemosiderin) looks like DAB; only very dark deposits are caught.
7. **Pre-analytics are invisible in the image** (fixation, cold ischaemia, decalcification); they are enforced
   only through the review form.
8. **A single uploaded field has no magnification metadata**; the server assumes the configured site µm/px.
9. **Control-based stain calibration** is available but unvalidated on real control slides and off by default.
10. **CPU throughput**: one whole slide takes 4–11 minutes; concurrent slide analyses queue.
11. **Not a certified medical device**; no CE/CDSCO/FDA clearance. For research and workflow support.

## 10. Source code map

| Path | Contents |
|---|---|
| `app/` | Server, accounts (`auth.py`), analysis, cells, pre-score, guidance, decision support, explanations, review record, case store, PDF reports, admin CLI, learning |
| `wsi/` | Whole-slide reader, artefact/control exclusion, slide analysis, slide reports, slide routes |
| `models/` | ResNet18-UNet (`unet_seg.py`), multi-task pre-score model (`multitask.py`) |
| `preprocessing/` | Stain deconvolution, tissue detection, tiling, classical baseline |
| `training/` | Datasets, splits, losses, pseudo-labels, training loops (v1 CPU, v2 GPU) |
| `evaluation/` | Conformal prediction, safety gate, ASCO/CAP mapping, stain-shift and cross-site analysis |
| `ui/` | React web portal source (`src/`), build config |
| `configs/` | All YAML/JSON configuration: preprocessing, training, cell parameters, site validation, learning |
| `scripts/` | Command-line tools: training, evaluation, calibration, packaging, slide scoring |
| `tests/` | 563 automated tests |
| `deploy/sdc/` | SDC deployment kit: compose file, Caddyfile, install/backup/smoke-test scripts |
| `docs/` | Design documents (deployment, accounts, whole slides, field quality, learning, review) |
| `Dockerfile`, `docker-compose.yml` | Container build and the generic single-host compose file |
