# Continual learning from cases and annotations

Status: built 2026-10-03. Code `app/learning/`, settings `configs/learning.yaml`,
admin page **Admin console → Learning**, tests `tests/test_learning.py`,
evidence `scripts/learning_simulation.py`.

## What it does

The pre-score model learns from this hospital's own work:

1. **Every analysed field and whole slide is stored** (`artifacts/learning/cases/`):
   the model's tile features, the tile grid, the model version, and the image
   itself (`store_images`). The case id is a hash of the image, so reviews and
   annotations made later attach to the right case.
2. **Signed pathologist reviews become labels.** The newest *final* review of a
   case gives its score; an amendment replaces the earlier label; drafts,
   preliminary reviews and "cannot assess" never become labels.
3. **Region annotations become tile labels.** Every model tile covered at least
   one quarter by an annotated box gets that box's score. These teach the
   per-region grades, which also feed the slide- and field-level result.
4. **A candidate version is trained** on demand from the admin page. Only the
   model's final stage changes: the attention pooling and score head (~66k
   parameters), trained on stored, frozen image features with:
   * replay of training-site cases in every step (so it keeps what each grade means);
   * class balancing;
   * an anchor penalty towards the version being updated;
   * annotation tiles as a second training signal.

   This takes seconds to minutes on the server's CPU. The image encoder itself
   is only retrained through the GPU workflow (docs/V2_TRAINING_PLAN.md),
   using the stored images.
5. **The candidate is judged against gates fixed in advance**
   (`configs/learning.yaml`):

   | Gate | Rule |
   |---|---|
   | Enough data | ≥ 40 signed cases, ≥ 3 per grade |
   | No forgetting | accuracy on the LOCKED training-site reference set drops ≤ 1 point, QWK ≤ 0.01 |
   | Real gain here | on this site's signed cases, cross-validated (5 folds), accuracy rises ≥ 2 points |
   | No new big errors | errors of two or more grades do not increase |

6. **An administrator activates it.** Passing the gates only makes a version
   eligible. Activation is recorded in the audit log with the person and time;
   new analyses use it at once, and every analysis records the version that
   produced it. Any earlier version (including the shipped `v0`) can be
   re-activated (rollback).

### Why it does not update itself after every slide

A model that changed its own weights from each case and went live
automatically could be shifted by one mislabelled case or a bad annotation.
Nobody would notice, and nobody could say afterwards which model produced which
report. Regulators treat such "adaptive" medical AI as needing a controlled
change plan. Here, learning is continuous (every case is collected), but
releases are discrete, tested and approved.

### What changes when a version is activated

* **Prediction sets switch off until recalibrated.** The 90% conformal set was calibrated for one model
  version at one site (`prescore_sets.json`, `head_version`). After activating a version, **Admin console ->
  Learning -> Prediction sets** shows that the set is off and offers **Recalibrate for vN**. That button
  (`POST /api/admin/learning/recalibrate`, audited as `learning.sets_recalibrated`) scores every signed local
  case with the live version, takes the least-ambiguous-set threshold for 95 / 90 / 80 %, and rewrites
  `prescore_sets.json` for this site and version. It needs at least `calibration.min_cases` signed cases
  (default 25, the number PHASE4.md found enough to restore coverage at a new hospital) and writes nothing below
  that; a threshold the data cannot support (fewer than ceil((1 - alpha) / alpha) cases) is stored as 1.0, which
  keeps every grade in the set -- the honest "cannot narrow this down". The previous file is kept in
  `artifacts/learning/sets_history/`. The command-line route, for an offline calibration, is still
  `scripts/calibrate_prescore_sets.py --site ... --cases ... --head-version vN`.

## Results: does it learn?

`scripts/learning_simulation.py` (results in `artifacts/learning/simulation_run_a.{json,md}`)
uses Run A, which never saw BCI, with BCI as a new hospital. 200 BCI images are
a fixed untouched test set; the rest arrive as signed cases in random order
(10 orders). It applies the same training and gates as the live system.

_Results table filled in below after the run._

## Operating it

* Off switch: `enabled: false` in `configs/learning.yaml` (cases stop being stored).
* Images: `store_images: false` keeps features only. The encoder then cannot be
  retrained from local data later.
* Back up `artifacts/learning/` with the rest of `artifacts/`.
* The locked reference set ships as `artifacts/learning/reference_run_b.npz`
  (`scripts/extract_learning_features.py --sets replay,reference`). It belongs to
  the deployed checkpoint: a new checkpoint needs a new reference file.
