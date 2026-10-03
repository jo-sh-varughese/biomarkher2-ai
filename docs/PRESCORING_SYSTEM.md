# BioMarkHER2 pre-scoring and explanation system

Built 2026-10-02. What the pathologist gets for every analysed field, how
each part is computed, how well it has been measured to work, and the safety
rules around it.

## What the pathologist sees

In the viewer (Analysis page, new top card + three new image views) and in
the PDF report (`/api/report`, three pages):

| Part | What it shows | Module |
|---|---|---|
| **AI pre-score** | Suggested IHC grade (0 / 1+ / 2+ / 3+), probability of each grade, confidence, runner-up, borderline flag | `app/prescore.py` |
| **Suggested next steps** | ISH required / recommended / not indicated by IHC, with the reasons (cautions) and concrete next steps | `app/guidance.py` |
| **Cell-level ASCO/CAP evidence** | Every detected cell classified by membrane completeness and intensity; % of cells at 0 / 1+ / 2+ / 3+; the 10% rule result; HER2-low / ultralow | `app/cells.py` |
| **Cell membrane map** (view "Cells") | Each cell's membrane outlined in its category colour | `app/cells.py` |
| **AI evidence heatmap** (view "AI evidence") | Grad-CAM: which pixels drove the pre-score | `app/prescore.py` |
| **Regional pre-scores** (view "Regions") | Each 512 px region's own pre-score and its weight in the overall one; heterogeneity | `app/prescore.py` |
| Existing measurements | Intensity map, DAB heatmap, threshold baseline, confidence map, area percentages | `app/analysis.py` |
| **Report sign-off block** | Final score, ultralow option, ISH ordered, control acceptable, invasive tumour present, signature | `app/report.py` |

## How well each part works (measured, held-out data)

| Component | Data | Accuracy | QWK | Notes |
|---|---|---|---|---|
| AI pre-score (Run B, ResNet-50) | 1,904 holdout patches, training site | **92.3%** | **0.975** | 0.2% off by 2+ grades |
| AI pre-score at an unvalidated hospital (Run A on BCI) | 977 images | 48-55% | ~0.31 | most confident answers were the worst -> the safety gate |
| Cell-level ASCO/CAP evidence | 100 holdout patches | 72.0% | 0.844 | recall 0 / 1+ / 2+ / 3+ = 64 / 52 / 76 / 96%; weakest at 0 vs 1+ |

Cell cut points were calibrated on 80 training-split patches
(`scripts/calibrate_cells.py`, stored in `configs/cell_params.json`) and the
held-out figure was measured once.

## ISH guidance logic (ASCO/CAP 2018, affirmed 2023)

* Pre-score 2+ -> **ISH required** (reflex ISH, or repeat IHC on a new specimen).
* Pre-score 3+ -> ISH not required **only if** confidence >= 70%, not
  borderline, cell evidence agrees, no regional heterogeneity and no cell-level
  flags; otherwise **ISH / second review recommended**.
* Pre-score 0 / 1+ -> negative range; **recommended** when P(2+) >= 25%, when
  >10% of cells reach 2+ or more, or when AI and cells disagree by 2 grades.
* 1+ -> HER2-low note; 0 with faint incomplete staining in >0-10% of cells ->
  HER2-ultralow note; 0 -> "distinguish 0 from 1+ carefully".
* Always: verify the on-slide control, score invasive tumour only; too few
  cells -> score more fields; heterogeneity -> review regions individually.

## Safety rules (enforced by tests)

* The pre-score is shown only when the **site safety gate**
  (`evaluation/safety_gate.py`) has validated the site against a local
  validation record (defaults: >=100 cases, >=90% accuracy, QWK >=0.85, <=1%
  off by 2+ grades -- for the pathologists to set). The training site is
  validated by `configs/site_validation/her2_ihc_40x.json` (Run B holdout).
* Unvalidated site -> pre-score **withheld**, evidence and guidance still
  shown, and the withheld pre-score logged to `--shadow-log` so the site can be
  validated later. Unknown magnification -> **blocked**.
* `--research-prescores` shows pre-scores at an unvalidated site, each with a
  red "RESEARCH MODE ... never for patient care" warning.
* Every pre-score carries `requires_pathologist_confirmation: true`; no field
  is a verdict or diagnosis (`tests/test_app.py`, `tests/test_prescoring.py`).

## Running it

Training site (validated, pre-scores shown) -- the defaults:

    python -m app.server

A new hospital (e.g. Kottayam), first fingerprint its images, then run in
shadow mode until validated:

    python scripts/site_fingerprint.py --site-dir <kottayam images> --site-mpp <scanner um/px> --out artifacts/fingerprints/kottayam
    python -m app.server --site-name "GMC Kottayam" --site-mpp <um/px> \
        --site-fingerprint artifacts/fingerprints/kottayam/fingerprint.json --site-validation ""

After pathologists have reviewed enough cases, build a validation record from
the shadow log and their reviews, and pass it with `--site-validation`.

## Limitations

* Field (patch) level, not whole-slide: tumour regions are not yet detected,
  so every detected cell counts, including stroma and normal ducts.
* Cell cut points are calibrated against patch labels, not pathologist cell
  annotations.
* The pre-score has only been validated at its training site; elsewhere it is
  withheld by design.
* Not a certified medical device.
