---
title: Handover Index
subtitle: Project "HER2 Biomarker" (BioMarkHER2), handover to SDC
doc_id: BMH-SDC-00
---

# Handover Index

| | |
|---|---|
| Project | HER2 Biomarker: BioMarkHER2 HER2 IHC pre-scoring and review portal |
| To | State Data Centre (SDC), Kerala; K-DISC |
| From | BioMarkHER2 project team (Johan S Varughese) |
| Release | `sdc-2026.11.11` |
| Date | 11 November 2026 |

This package answers SDC's request for the handover of the project. Each requested item is listed below with where
it is in the package. Start with the **Deployment Guide** to install, then use the manuals.

## 1. Requested items and where to find them

| SDC request | Delivered | Location |
|---|---|---|
| **Source code**: complete, all modules, scripts, dependencies | Full source tree of release `sdc-2026.11.11`, dependency lists, file manifest with checksums | `01_Source_Code/` |
| **Sample datasets** for training, validation, testing | **Not included, as agreed with SDC** (only the model is required). The training and test data are public datasets, described in the Technical Documentation | *Technical Documentation* §4.1 |
| **Model details**: architecture, name, version, weights / checkpoints, configuration | Both checkpoints and calibrations with SHA-256; evaluation outputs; configuration files; model descriptions | `02_Models/`; *Technical Documentation* §3 |
| **Development methodology**: preprocessing, annotation, training, validation, testing, inference | Described step by step | *Technical Documentation* §2, §4, §5 |
| **Performance evaluation**: results, metrics, confusion matrices, known limitations | Held-out and cross-site results, confusion matrices, K-DISC first look, limitations | *Technical Documentation* §6, §9 |
| **Technology stack**: languages, frameworks, libraries, versions, dependencies, hardware, APIs, integration | Pinned versions, hardware sizing, API reference | *Technical Documentation* §7, §8 |
| **Deployment documentation**: installation, configuration, Docker files / scripts, dependencies, step-by-step guide for SDC | Offline-installable bundle (images, models, scripts) and an SDC-specific guide, tested end to end | `04_Deployment/`; *Deployment Guide* (BMH-SDC-02) |
| **User and Administrator manuals** with screenshots: access, user management, image / WSI upload and analysis, result interpretation, report generation, administrative settings, troubleshooting | Two manuals with screenshots from the release | `05_Manuals/`; BMH-SDC-03, BMH-SDC-04 |
| **Knowledge transfer and demonstration** | Session plan, live demonstration script, maintenance checklist, model-update procedure. Sessions to be scheduled with SDC | `06_Knowledge_Transfer/`; BMH-SDC-05 |

## 2. Package contents

```
BioMarkHER2_SDC_Handover_2026-11-11/
├── 00_Handover_Index.pdf                     this document
├── 01_Source_Code/
│   ├── biomarkher2-sdc-2026.11.11-source.zip  complete source (code, configs, tests, docs, Dockerfile, deploy kit)
│   ├── SOURCE_MANIFEST.txt                    every file with its SHA-256
│   ├── requirements.txt                       pinned Python dependencies
│   └── package-lock.json                      pinned web-portal dependencies
├── 02_Models/
│   ├── biomark_models.tgz                     both model checkpoints + calibrations (≈185 MB)
│   ├── MODELS.sha256
│   └── evaluation/                            held-out metrics and confusion matrices (JSON/CSV)
├── 03_Technical_Documentation/                Technical Documentation (PDF, DOCX)
├── 04_Deployment/
│   ├── Deployment_Guide (PDF, DOCX)
│   └── sdc_bundle/                            images.tar.gz, biomark_models.tgz, deploy/, SHA256SUMS
├── 05_Manuals/                                User Manual, Administrator Manual (PDF, DOCX)
├── 06_Knowledge_Transfer/                     Knowledge Transfer Plan (PDF, DOCX)
└── SHA256SUMS.txt                             checksums of every file in the package
```

## 3. Verification performed before handover

* **Automated tests:** the full test suite passes on this release (pytest).
* **Deployment rehearsal:** the exact `sdc_bundle` was installed with `install.sh` on a clean Linux Docker host;
  `smoke_test.sh` passed (HTTPS, redirect, HSTS, health, model checksums, port 8000 closed, slides writable), and a
  backup was taken and restored. The stack was also run with a 6 GB memory cap to analyse a full K-DISC slide
  (peak 1.4 GB, 4.3 min). The manuals' screenshots come from this installation.
* **Offline operation:** both models load with networking disabled, as on the SDC VM after the internet window
  closes.
* **Defects found and fixed during the rehearsal** (each with a regression test):
  1. the server tried to download ImageNet weights at start-up and could not start without internet;
  2. the case log listed a HER2 category for images the quality gate had refused (*Not assessable*);
  3. whole-slide analysis of a K-DISC slide used more than 6.9 GB of memory and was killed; it now peaks at 1.4 GB;
  4. the generic `docker-compose.yml` mounted the slide folder read-only, so slide uploads failed in Docker.

## 4. Important notes

1. **Clinical status.** BioMarkHER2 is a pre-scoring and decision-support aid for research and workflow support. It is
   not a certified medical device. A pathologist signs every score.
2. **Shadow mode at the SDC.** The AI pre-score is validated only at its training site, and at an unseen hospital
   its accuracy fell to 48–55%. At the SDC it is therefore **withheld** until a local validation study (about 100 signed
   cases across all grades) is completed. Cell evidence, measurements and ISH guidance are available from day one.
3. **K-DISC ground truth.** The four K-DISC slides came without pathologist scores, so accuracy at K-DISC has not been
   measured. Labelled slides across 0 / 1+ / 2+ / 3+ are needed (Knowledge Transfer Plan §5.1).
4. **Credentials.** No passwords, keys or VPN credentials are included in this package. The demonstration accounts
   in the screenshots exist only on a test installation.
5. **Third-party data and licences.** No training or test data are included. The models were trained on public
   datasets (Technical Documentation §4.1). Software dependencies are open source; their licences apply.

## 5. Contact

Johan S Varughese, BioMarkHER2 project team, for questions during and after the knowledge-transfer sessions.
