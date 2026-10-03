# Whole-slide analysis and invasive-tumour detection

Status: built 2026-10-02, not committed. Code in `wsi/`, server routes in
`wsi/server_routes.py`, UI in `ui/src/pages/Slides.jsx`, tests in
`tests/test_wsi.py`.

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
3. **Maps invasive tumour** (`wsi/tumour.py`): a ResNet-50 U-Net applied to
   512 µm tissue blocks at 0.5 µm/px. Classes: other tissue, invasive tumour,
   in-situ tumour (DCIS), healthy glands. If a slide has more blocks than the
   CPU budget (`--slide-max-tumour-blocks`, default 400), a regular grid
   sample is taken and the rest are marked **not evaluated**, never treated
   as tumour-free.
4. **Chooses fields**: up to `--slide-max-fields` (default 40) fields of
   1024 px at 0.24 µm/px (~246 µm, the training scale of the pre-score
   model), centred on invasive-tumour blocks and spread over the tumour.
5. **Per field**: cell-level ASCO/CAP membrane evidence (`app/cells.py`)
   counted **only inside invasive tumour**, since ASCO/CAP scores invasive
   tumour cells only and DCIS/normal glands are excluded; plus the pre-score
   model's tile embeddings and per-tile grades.
6. **Slide level**: one AI pre-score by attention pooling over every tumour
   tile analysed; ASCO/CAP percentages over all invasive cells measured;
   heterogeneity across fields; the highest-weighted fields as **hotspots**
   that the viewer zooms to on click.
7. **Safety**: the same site gate as single fields (validated / shadow mode
   / blocked). Slides scanned coarser than 0.5 µm/px (below ~20×) **never get
   a pre-score**, and their cell evidence is flagged unreliable, because
   membrane completeness cannot be judged at 10×.
8. **Report**: `GET /api/slides/<id>/report` produces a slide PDF (overview with
   tumour map, grade map, hotspots, cell evidence, ISH guidance).

## Why the tumour model sees only haematoxylin

No public dataset has invasive-tumour annotations **on HER2 IHC**. Public
tumour annotations are on H&E (TIGER, BCSS). The tissue architecture that
separates invasive carcinoma from stroma, DCIS and normal glands (nuclear
crowding, gland formation, nuclear size and atypia) lives in the
haematoxylin channel, which H&E and IHC share. So both training images (H&E)
and slides at inference (IHC) are colour-deconvolved and **re-rendered as
haematoxylin only** (`haematoxylin_image`). The model never sees eosin or DAB,
so it cannot learn "brown = tumour", which would bias HER2 scoring towards
positive. A unit test checks that adding DAB does not change the model input.

## Training data and protocol (fixed before training)

* **TIGER WSIROIS tissue-cells** (AWS Open Data `tiger-training`, CC BY-NC
  4.0): 1,879 annotated ROIs from TCGA, Radboud and Jules Bordet breast
  cancer slides at ~0.5 µm/px. TIGER labels map to ours:
  invasive tumour → invasive; DCIS → in-situ; healthy glands → glands;
  tumour-associated stroma, inflamed stroma, necrosis, rest → other;
  unannotated → ignored.
* Split **by slide** (not by ROI), 15% of slides held out, stratified TCGA vs
  non-TCGA.
* ResNet-50 encoder with Lunit Barlow Twins pathology weights, 3-channel
  haematoxylin input, 512 px crops, rotation/flip/blur and haematoxylin
  strength (×0.75–1.3) augmentation, cross-entropy + Dice, 25 epochs, ≤60
  min. Selection by validation IoU of invasive tumour.
* **IHC transfer check** after training: predicted invasive fraction of
  tissue on HER2-IHC-40x holdout and BCI test patches (both cut from tumour
  regions, so a high fraction is expected; a low one means H&E→IHC transfer
  failed). Validation precision on H&E is the negative control (how much
  non-tumour tissue is called invasive).
* `scripts/train_tumour.py --config configs/tumour_seg.yaml`; pod runs via
  `scripts/pod/run.sh configs/tumour_seg.yaml` (downloads TIGER itself with
  `scripts/pod/fetch_tiger.sh`).

## Results

GPU run 2026-10-02 (secure A40, 25 epochs in 37 min, $0.35 including two
faulty-host retries). Numbers from `artifacts/tumour/results.json`.

**H&E validation (26 held-out TIGER slides, best epoch 10)**

| | value |
|---|---|
| Invasive tumour IoU | 0.67 |
| Invasive precision / recall / F1 | 0.80 / 0.81 / 0.80 |
| Other tissue IoU | 0.78 |
| In-situ (DCIS) IoU | **0.00** |
| Healthy glands IoU | **0.00** (0.05–0.09 in late epochs, not selected) |

The model **does not separate DCIS or normal glands from invasive tumour.**
They are 5% and 3% of training pixels and it never learned to predict them.
DCIS is therefore likely to be included in the "invasive" map. This is the
main reason the pathologist must check the tumour map, and the first thing to
improve.

**IHC transfer check (patches cut from tumour regions)**

| | assumed µm/px | mean invasive fraction of tissue | patches > 30% invasive |
|---|---|---|---|
| HER2-IHC-40x holdout (n = 200) | 0.24 | 0.42 | 73% |
| BCI test (n = 187) | 0.46 | 0.05 | 4% |

BCI looked like a transfer failure. Investigating it found two separate
things:

1. **Grey-cast scans.** Many BCI images have no white background, and colour
   deconvolution turned the grey into "haematoxylin everywhere". Fixed with a
   white-point correction before deconvolution (`white_balance`, a no-op on
   normal scans; regression test added).
2. **Scale.** The model is sensitive to magnification. On 24 BCI patches the
   invasive fraction is 2% at the documented 0.46 µm/px, 10% at 0.7 and 30% at
   1.0. Nuclei in the patch datasets also measure inconsistently against TIGER
   at their stated scales (HER2-IHC-40x ≈ 2.2×, BCI ≈ 0.7× TIGER), so the patch
   sets' stated µm/px are probably not reliable. Real whole slides carry µm/px
   from the scanner, so the pipeline reads them at the right scale, but a
   model that tolerates scale error is still wanted (next step: retrain with
   ×0.7–1.4 scale augmentation, ≈ $0.4).

**Real whole slide: ACROBAT case 39 HER2 IHC** (Karolinska, CC BY 4.0;
36,864 × 19,712 px, 0.907 µm/px, 10×)

Run end to end in the portal (Chromium, Playwright): slide list, Deep Zoom
viewer (67 tiles, 0 failures), analysis with live progress (12 min on CPU,
150 tumour blocks, 12 fields), overlays, hotspots and PDF report, with no
browser errors. Three safety problems surfaced and were fixed:

| Problem on the real slide | Effect | Fix |
|---|---|---|
| On-slide **HER2 control cores** detected as invasive tumour | Patient's cells ≥2+ = **4.0%** (control cells); after exclusion **0.0%** (≥1+ 0.1%): tumour nests are unstained | `wsi/artefacts.find_control_cores`: small, compact tissue pieces standing ≥1.5 mm apart from the main tissue are excluded, drawn teal and flagged |
| **Blue ink / mounting film** at the coverslip edge partly called tumour | Spurious tumour area | `blue_cast`: brightest 10% of a block > 15 B−R units bluer than glass → artefact (tissue measured −11..+4, ink +20..+32); drawn grey and flagged |
| 10× slide got the guidance "ISH not indicated by IHC" | An unassessable slide read as reassuring | `recommend(..., assessable=False)` → "Not assessable at this magnification: rescan at 20×/40×" |

A fourth problem was in the server, found while testing: renaming the site
(`--site-name`) kept the training site's validation record (default
`--site-validation`), so any hospital came up as **validated**. A validation
record now counts only for the site it names; otherwise the gate falls back
(here: blocked, since µm/px is then unknown). Regression test added.

## Running it

```
biomark --slide-root data/slides --tumour-model artifacts/tumour/best.pt \
        --prescore-run artifacts/v2/run_b/best.pt
```

Options: `--slide-mpp` (for slides without µm/px metadata),
`--slide-max-fields`, `--slide-max-tumour-blocks`. Without `--tumour-model`
the pipeline still runs, uses all tissue, and says on screen and in the
report that tumour was **not segmented**.

## Next steps (in order of value)

1. **DCIS vs invasive.** Retrain with stronger weighting of in-situ and glands
   (or a separate invasive-vs-in-situ head) plus scale augmentation; one GPU
   run of ≈ $0.4.
2. **Kottayam check.** Run 5–10 Kottayam HER2 slides through the Slides page
   in shadow mode; a pathologist marks each tumour map and exclusion as
   right or wrong. This is the real test of H&E→IHC transfer.
3. **Use the control cores.** They are now located automatically; measuring
   their DAB gives per-slide stain calibration
   (evaluation/control_calibration.py) instead of discarding them.
4. **Speed.** About 12 min per slide on CPU, dominated by tumour detection;
   a GPU or a coarser first pass would bring it to about 1–2 min.

## Limits, said plainly

* The tumour model has never seen a HER2 IHC tumour annotation. Its IHC
  behaviour is checked only indirectly (transfer check above and visual review
  of real IHC slides). A pathologist must check the tumour map, which is
  shown as an overlay for that reason.
* Public HER2 IHC whole slides with HER2 scores at ≥20× are not openly
  available. ACROBAT (Karolinska, CC BY 4.0) has HER2 IHC WSIs but only at
  10× (0.92 µm/px), so they test tumour detection and the viewer, and they
  correctly receive **no** pre-score. Kottayam slides are the first real
  ≥20× HER2 WSIs the system will see, and the site gate keeps the pre-score
  in shadow mode there until locally validated.
* CPU speed: a whole slide on CPU takes minutes (tumour blocks are capped);
  the cap and the "not evaluated" share are reported.
