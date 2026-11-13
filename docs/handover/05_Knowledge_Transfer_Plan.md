---
title: Knowledge Transfer Plan
subtitle: Sessions, live demonstration script, maintenance and model updates
doc_id: BMH-SDC-05
---

# Knowledge Transfer Plan

This document plans the knowledge-transfer (KT) sessions requested by SDC and is the handout for them. It covers the
application architecture, the model workflow, a live demonstration, system operation, routine maintenance and future
model updates.

## 1. Sessions

Two sessions, about 2½ hours in total, held over VPN screen-share or on site after the system is installed at the SDC.
The demonstration runs on the SDC instance itself.

| Session | Audience | Duration | Content |
|---|---|---|---|
| **A. Technical and operations** | SDC infrastructure / operations team, K-DISC technical lead | 90 min | Architecture, deployment, operation, backups, security, troubleshooting, updates |
| **B. Application and clinical workflow** | K-DISC, pathologist leads, administrators | 60 min | Live demonstration, result interpretation, administration, site validation |

**Prerequisites:** the system installed and passing `smoke_test.sh` (Deployment Guide §7); one administrator, one
pathologist and one viewer account for the demonstration; demonstration field images (brought by the presenter; not part of the package);
one K-DISC slide already uploaded and analysed (to avoid waiting during the session).

## 2. Session A: technical and operations (90 min)

| Time | Topic | Material |
|---|---|---|
| 0:00 | Purpose, intended use, and what the system must never do | Technical Documentation §1 |
| 0:10 | Architecture: two containers, one VM, no outbound calls; where data lives | Technical Documentation §2, Figure 1 |
| 0:25 | Models and the analysis pipeline: quality gate → cells → stain map → pre-score → site gate → ISH guidance | Technical Documentation §2.1, §3 |
| 0:40 | Live walk-through on the VM: `/opt/biomarkher2`, `.env`, `docker compose ps/logs`, health check, `smoke_test.sh` | Deployment Guide §4–7, §9 |
| 0:55 | Backups and restore (run `backup.sh`, inspect the archive, explain restore) | Deployment Guide §8 |
| 1:05 | Security: ports, TLS certificate installation, accounts, audit, container user | Deployment Guide §5.1, §12 |
| 1:15 | Updates: application image, model files, rollback; site validation | Deployment Guide §10–11 |
| 1:25 | Troubleshooting table; questions | Deployment Guide §13 |

## 3. Session B: live demonstration script (60 min)

Each step lists what to do and what the audience should see.

| # | Do | Expected |
|---|---|---|
| 1 | Open `https://<host>`; sign in as the administrator | Overview page; yellow "does not make the diagnosis" banner |
| 2 | Admin console → Users → **Add user** (pathologist, set password) | One-time details screen; user shows *Temporary password* |
| 3 | Admin console → **System** | Models loaded; secure cookies on; readiness 4/5 until a second administrator is added (then 5/5) |
| 4 | Sign in as the pathologist in a private window; choose a new password | Forced password change, then Overview |
| 5 | **Field analysis** → upload `3_HER2_score_2plus.png` → Analyse | Site badge *shadow mode*; "AI pre-score withheld at this site"; cell evidence *IHC 2+*; **ISH required** |
| 6 | Switch views: Cells, More views → Intensity map, Threshold baseline | Membrane map coloured by category; model vs classical baseline |
| 7 | Evidence and details → ISH decision evidence, Why this result | ASCO/CAP step, evidence for/against, 10% cut-off proximity, stability |
| 8 | **PDF report** | Multi-page PDF with images, ISH page, caveats, sign-off block |
| 9 | **Open pathologist review**; fill specimen, control, score 2+, ISH ordered; **Sign and finalise** | Record *Signed (final) v1*; history shown; score was not pre-filled |
| 10 | Upload `5_false_positive_out_of_focus.png` | **Not assessable**: too few cells, out of focus; no grade, no ISH suggestion |
| 11 | **Case log** → open the 2+ case | Every analysis and sign-off; the out-of-focus case listed *Not assessable* |
| 12 | **Whole slides** → open the pre-analysed K-DISC slide | Viewer; excluded control core; field grades; hotspots; slide ISH guidance |
| 13 | Show **Mark tumour regions** (no need to re-run) | How scoring is restricted to invasive tumour |
| 14 | Sign in as the viewer | Review form locked with an explanation |
| 15 | Admin console → **Audit log**, filter "sign-ins" and "exports" | Every action of the demonstration recorded |
| 16 | Admin console → **Learning** | Collected cases; gates; why activation is manual |
| 17 | Close: site validation plan and what K-DISC needs to provide | §5 below |

## 4. Routine maintenance (operations checklist)

| Frequency | Task | How |
|---|---|---|
| Daily | Confirm the backup ran | `ls -lt /opt/biomarkher2/backups | head -3` |
| Weekly | Health and disk | `bash /opt/biomarkher2/smoke_test.sh`; `df -h` |
| Weekly | Review failed sign-ins and lockouts | Admin console → Audit log, category *security* |
| Monthly | OS security updates (then `docker compose up -d`) | SDC patching process |
| Monthly | Remove leavers; export the audit log | Admin console → Users, System → Exports |
| Monthly | Slide retention | Archive or delete old slides from `slides/` per policy |
| Quarterly | Test a restore | Deployment Guide §8 |
| On certificate renewal | Replace `certs/*.pem`; recreate the proxy | Deployment Guide §5.1 |

## 5. Future model updates

There are three ways the AI can change. Each has a different owner and control:

| Path | What changes | Who | Control |
|---|---|---|---|
| **1. Local learning** (in the portal) | Only the pre-score head (≈66k parameters), from this hospital's signed cases | Administrator | Fixed gates in `configs/learning.yaml`; manual, audited activation; rollback to any version |
| **2. New model release** | Model files (`best.pt`) and calibration | Development team | New `biomark_models.tgz` with checksums; site validation repeated; Deployment Guide §11.2 |
| **3. New application release** | Code and image | Development team | New image tag; smoke test; rollback by tag; Deployment Guide §11.1 |

### 5.1 What is needed to validate and improve the model at K-DISC

1. **Pathologist scores for slides.** The four K-DISC slides have none. Accuracy here cannot be stated without them.
2. **Slides across all grades**, especially 0, 1+ and 2+. The slides received so far are strongly 3+ or unreadable.
3. **At least 100 signed cases** in the portal (shadow mode) to build the site validation record (Deployment
   Guide §10); 40 or more signed cases with 3 or more per grade enable a local learning candidate.
4. **On-slide control information**: if the laboratory's control is a known 3+, declaring it enables per-slide stain
   calibration (`--control-level 3+`) after a local reference is built.
5. **Scanner details** (model, µm/px) for any scanner other than the Medprime scanner, because the pre-score is
   scale-sensitive.

### 5.2 Retraining the full model (development workflow)

Retraining the image encoder needs a GPU workstation or rented GPU (about 1 hour per run). Steps, all in the source
code:

1. Export locally stored cases (`artifacts/learning/cases/`) and signed reviews.
2. Add them to the training configuration (`configs/v2_*.yaml`), keeping the HER2-IHC-40x holdout untouched.
3. Train (`scripts/train_v2.py`), evaluate (`scripts/eval_v2.py`) against fixed targets, recalibrate prediction sets
   (`scripts/calibrate_prescore_sets.py`) and rebuild the learning reference (`scripts/extract_learning_features.py`).
4. Package (`scripts/package_models.sh`) and deploy as path 2. Re-run site validation.

## 6. Handover of responsibilities (proposed)

| Area | Owner after handover |
|---|---|
| VM, OS patching, network, firewall, certificates, backups off-VM | SDC |
| Docker runtime, containers, `.env`, running `smoke_test.sh` | SDC operations |
| User accounts, settings, audit review, learning activation | K-DISC-nominated portal administrators |
| Clinical use, site validation study, signing scores | Pathologists / K-DISC clinical lead |
| Code and model changes | Development team (or successor), via new releases |

## 7. Questions to settle during KT

* Final DNS name and certificate authority for the portal.
* How pathologists reach the VM (individual VPN accounts, or a site-to-site link from the hospital).
* Backup destination off the VM and retention periods for slides and records.
* Whether SDC requires a security audit (e.g. CERT-In empanelled auditor) before go-live.
* Who at K-DISC administers accounts, and who leads the site validation study.
