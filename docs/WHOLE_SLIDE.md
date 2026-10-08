# Whole-slide analysis

Status: built 2026-10-02; **revised 2026-10-06** — the invasive-tumour segmenter was
removed (it is not one of the project's four objectives) and the on-slide
control is now measured and, when declared, used for per-slide stain
calibration. Code in `wsi/`, server routes in `wsi/server_routes.py`, UI in
`ui/src/pages/Slides.jsx`, tests in `tests/test_wsi.py`.

## What it does

A pathologist opens a scanned slide (`.svs`, `.ndpi`, `.tiff`, `.mrxs`, ...)
in the portal's **Slides** page, browses it at full resolution
(OpenSeadragon Deep Zoom), and presses **Analyse slide**. The server then:

1. **Reads the slide at physical resolution** (`wsi/reader.py`). Every read
   is expressed in µm/px, not in pyramid levels, so a 0.25 µm/px Aperio scan
   and a 0.46 µm/px Hamamatsu scan are resampled to the same scale before
   anything looks at them. µm/px comes from the slide metadata; a slide
   without it needs `--slide-mpp`.
2. **Finds tissue** on an 8 µm/px overview (saturation + optical-density
   threshold).
3. **Excludes what is not the patient** (`wsi/artefacts.py`): blue ink and
   mounting film (checked block by block, by colour alone: no model) and
   **on-slide control cores** (small, compact tissue pieces standing ≥1.5 mm
   apart from the main tissue). They are drawn on the overlay and listed in
   the flags, never silently dropped.
4. **Measures the control** and, if allowed, uses it (see below).
5. **Chooses fields**: up to `--slide-max-fields` (default 40) fields of
   1024 px at 0.24 µm/px (~246 µm, the training scale of the pre-score
   model), spread over the usable tissue.
6. **Per field**: cell-level ASCO/CAP membrane evidence (`app/cells.py`) and the
   pre-score model's tile embeddings and per-tile grades.
7. **Slide level**: one AI pre-score by attention pooling over every tile
   analysed; ASCO/CAP percentages over all cells measured; heterogeneity
   across fields; the highest-weighted fields as **hotspots** that the viewer
   zooms to on click.
8. **Safety**: the same site gate as single fields (validated / shadow mode
   / blocked). Slides scanned coarser than 0.5 µm/px (below ~20×) **never get
   a pre-score**, and their cell evidence is flagged unreliable, because
   membrane completeness cannot be judged at 10×.
9. **Report**: `GET /api/slides/<id>/report` produces a slide PDF (overview with
   the excluded-tissue and grade maps, hotspots, cell evidence, ISH guidance).

**Tumour is not segmented.** ASCO/CAP scores invasive tumour cells only, but
the system does not find tumour: fields are spread over all usable tissue, so
stroma, in-situ carcinoma and normal ducts can fall inside a field and be
counted. Every result says so (a slide flag, the cell-evidence caveat and the
report), and the pathologist confirms that each field lies in invasive tumour.

## Using the on-slide control for stain calibration

Many HER2 slides carry a control of known score beside the patient's section.
It went through the same antibody, chromogen timing and scanner, so how dark
its DAB came out measures that run's staining strength directly
(`evaluation/control_calibration.py`, simulation in
`scripts/simulate_control_calibration.py`).

* **Measured always.** Up to six 40× fields are read inside each detected
  control core, and the DAB optical-density percentiles (p50–p99) of the
  DAB-stained pixels are reported in the result (`stain_control`) and in a slide flag.
* **Applied only with a declaration and a reference.** A control is known to be a
  particular HER2 level only if the laboratory says so. With
  `--control-level 3+` and a reference signature
  (`configs/control_reference.json`, built by `scripts/build_control_reference.py`),
  the strongest core is compared with the reference and the slide's DAB is
  rescaled by `gain = reference p90 / slide p90`. Without either, the control is
  reported and **not** used: a 0 or 1+ control read as 3+ would wrongly brighten the slide.
* **Refused when implausible.** A gain outside 0.33–3.0 means the control itself
  may have failed; the slide is flagged for a pathologist, not corrected.
* **What it changes.** Only the threshold-based **cell evidence** is rescaled. The
  neural pre-score always sees the field as scanned: it is trained with stain
  augmentation and simulation showed little left to correct there.
* **Honest limits.** The default reference is a *proxy*: pooled 3+ patient patches
  of the training site, not a control strip. A hospital should build its own
  reference from its own 3+ control crops
  (`scripts/build_control_reference.py --images <folder>`). Two or more control
  cores of different levels cannot be told apart, so only the strongest core is used.
  Calibration has been tested in simulation and on the synthetic slide in
  `tests/test_wsi.py`; it has not yet been validated on a real hospital's control slides.

## Findings on a real whole slide (ACROBAT case 39, HER2 IHC, Karolinska, CC BY 4.0; 36,864 × 19,712 px, 0.907 µm/px, 10×)

Run end to end in the portal (Chromium, Playwright) during the earlier,
tumour-model version: slide list, Deep Zoom viewer (67 tiles, 0 failures),
analysis with live progress, overlays, hotspots and PDF report, with no browser
errors. Three safety problems surfaced and were fixed, and all three still apply
to the current design:

| Problem on the real slide | Effect | Fix |
|---|---|---|
| On-slide **HER2 control cores** read as patient tissue | The control's cells were counted as the patient's (≥2+ share 4.0% with the control, 0.0% after exclusion) | `wsi/artefacts.find_control_cores`: small, compact tissue pieces standing ≥1.5 mm apart from the main tissue are excluded, drawn teal and flagged |
| **Blue ink / mounting film** at the coverslip edge | Spurious tissue and haematoxylin | `blue_cast`: brightest 10% of a block > 15 B−R units bluer than glass → artefact (tissue measured −11..+4, ink +20..+32); drawn grey and flagged. The check now runs on its own, without any model |
| 10× slide got the guidance "ISH not indicated by IHC" | An unassessable slide read as reassuring | `recommend(..., assessable=False)` → "Not assessable at this magnification: rescan at 20×/40×" |

A fourth problem was in the server, found while testing: renaming the site
(`--site-name`) kept the training site's validation record, so any hospital
came up as **validated**. A validation record now counts only for the site it
names. Regression test added.

## Running it

```
biomark --slide-root data/slides --prescore-run artifacts/v2/run_b/best.pt
# to use an on-slide 3+ control for stain calibration:
biomark --slide-root data/slides --control-level 3+ --control-reference configs/control_reference.json
```

Options: `--slide-mpp` (for slides without µm/px metadata), `--slide-max-fields`,
`--control-level`, `--control-reference`.

## Why the tumour segmenter was removed (2026-10-06)

It was an extra built beyond the four objectives (stain variation, stain-shift
conformal prediction, ASCO/CAP mapping, a deployable system), it was trained
on H&E (TIGER) and never saw a HER2 IHC tumour annotation, and it could not
separate DCIS or healthy glands from invasive tumour (IoU 0.00 for both on
held-out H&E; invasive-tumour IoU 0.67). Removed: `wsi/tumour.py`,
`scripts/train_tumour.py`, `configs/tumour_seg.yaml`, the TIGER download script,
the `--tumour-model` / `--slide-max-tumour-blocks` options and the tumour overlay.
The trained weights (`artifacts/tumour/best.pt`) were left on disk, unused and no longer
packaged. They can be deleted. The git history keeps all of the code.

## Limits, said plainly

* Tumour is not segmented (above): the pathologist confirms the scored area.
* Public HER2 IHC whole slides with HER2 scores at ≥20× are not openly
  available. ACROBAT has HER2 IHC WSIs but only at 10× (0.92 µm/px), so they test
  the viewer, the exclusions and the safety rules, and they correctly receive **no**
  pre-score. Kottayam slides are the first real ≥20× HER2 WSIs the system will see, and
  the site gate keeps the pre-score in shadow mode there until locally validated.
* Whole-slide time on CPU is no longer dominated by tumour detection; re-time it on the
  target hardware (the earlier ~12 min per slide included tumour detection).
* The control calibration needs a declared control level and a reference, and is
  unvalidated on real control slides (above).
