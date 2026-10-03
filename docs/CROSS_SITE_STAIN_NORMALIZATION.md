# Cross-institution stain-shift normalization: tested on BCI

Status (2026-10-01): **built, tested on a second institution's data, and it
measurably helps, but it does not close the gap.** Stain normalization
recovers about 10 points of four-class accuracy on the external dataset. The
model is still well below its in-domain accuracy there. Both facts are below,
with the numbers that support them.

## The question

Every result in this repo so far came from one source, HER2_IHC_40X. The
objective "cross-institutional stain shift normalisation" asks whether the
model still works on slides stained and scanned somewhere else, and whether
normalizing the stain fixes what breaks.

## Data

| | Source site (training) | Target site (external) |
|---|---|---|
| Dataset | HER2_IHC_40X | BCI, Liu et al., CVPR-W 2022 (MIT licence) |
| Scanner | unspecified | Hamamatsu NanoZoomer S60 |
| Magnification | 40x | about 20x |
| Labels | HER2 score of the source slide (filename prefix) | HER2 score from the pathology report |
| Used here | 200 fit-split images (score head, stain profile), 200 holdout images (in-domain reference) | 100 train-split images (dev: method choice + stain profile), 338 test-split images (all 38 score-0, 100 each of 1+/2+/3+) |

BCI was fetched per file from the Kaggle mirror
`aasimist/breast-cancer-immunohistochemistry-bci-dataset` into
`data/external/bci/IHC_{train,test}` (git-ignored, like all of `data/`).

## What was built

* `evaluation/cross_site.py`: **site-level** stain profiles and
  normalization. One Macenko stain matrix and one concentration scale per
  institution, estimated from a pooled pixel sample of unlabeled images.
  Every image from the target site gets the same transform, so the DAB
  difference between a 0 and a 3+ case is preserved. Per-image methods do not
  preserve it (see below).
* `scripts/cross_site_stain_eval.py`: the experiment (`profile`, `infer`,
  `report`). Outputs go to `artifacts/cross_site_bci/`.
* `tests/test_cross_site.py`: synthetic two-site tests (recovers the
  rendering stain matrix, undoes a site shift, preserves DAB ordering where
  per-image Macenko does not, quantile map is monotone).

## Two bugs fixed in `preprocessing/stains.py`

Found while building this, and they matter beyond it:

1. `estimate_macenko_stain_matrix` never oriented the principal eigenvector.
   numpy's sign is arbitrary, and when it came out negative the projected
   angles wrapped round ±π. The two "extreme" stain directions then collapsed
   onto one vector: H·DAB cosine was ~1.000 on 19 of 24 sampled real patches.
2. The H/DAB ordering compared red-minus-blue absorbance the wrong way round.
   Haematoxylin absorbs red (Ruifrok OD 0.65, 0.70, 0.29), so the old code
   returned DAB in the haematoxylin row.

After the fix, synthetic recovery is cosine > 0.9999 for both stains, and
real patches give two distinct vectors (H·DAB cosine 0.58–0.90). A
regression test is in `tests/test_stains.py`. **PHASE4.md's stain-variation
numbers and conformal stain-shift weights used the broken estimator.** They
are marked stale there and should be re-run before being quoted.

## Protocol (fixed before any target label was read)

* The segmentation model (`artifacts/phase2_unet_8epochs`) is **not**
  retrained or fine-tuned. Only the input stain changes.
* Patch score = a 3-feature logistic head (cumulative weak+ / moderate+ /
  strong tissue-area fractions from the model) fitted on 200 **source** images,
  then frozen.
* BCI images are centre-cropped to 512 px and upsampled 2x so physical scale
  matches 40x. This is identical in every condition.
* The normalization variant was chosen on BCI dev (train split) by highest
  accuracy, kappa as tie-break. The BCI test split was run after the choice.

## Measured stain shift

| | H vector | DAB vector | DAB 90th pct | DAB 99th pct |
|---|---|---|---|---|
| HER2_IHC_40X | 0.71, 0.67, 0.22 | 0.12, 0.44, 0.89 | 0.683 | 1.556 |
| BCI | 0.64, 0.58, 0.51 | 0.26, 0.48, 0.84 | 0.163 | 0.724 |

BCI's haematoxylin is bluer (18° apart) and its DAB is far weaker: the 99th
percentile is under half of ours, and the 90th is a quarter.

## Results (BCI test split, n=338)

| Condition | Accuracy | Balanced acc. | Macro-F1 | QWK |
|---|---|---|---|---|
| In-domain reference (our holdout, n=200) | 76.0% | 76.0% | 0.742 | 0.904 |
| BCI, no normalization | 29.9% | 37.5% | 0.292 | 0.380 |
| **BCI, site-level normalization (chosen)** | **39.9%** | **41.5%** | **0.396** | 0.304 |
| BCI, site-level + score head refit on 100 labelled BCI dev images | 40.5% | 47.3% | 0.407 | 0.381 |

Accuracy gain from normalization alone: **+10.0 points, paired-bootstrap 95%
CI [+4.7, +15.1]**. Balanced-accuracy gain: +4.0, CI [−1.7, +9.8] (not
significant). Per-class recall, none → normalized: 0: 79% → 50%, 1+: 14% →
31%, 2+: 39% → 50%, 3+: 18% → 35%.

Textbook per-image methods, run on the first 87–88 test images only (stopped
early once clearly harmful, to save CPU for the variants that could help):
per-image Macenko 22.7%, per-image Reinhard 21.8%, against 29.9% for doing
nothing. Both rescale each image to the same stain level, which erases the
DAB difference between a 0 and a 3+. Per-image Macenko also turned bare glass
into "tissue" (99% tissue fraction on some images).

## What this does not show

* **The gap is not closed.** 40% on BCI against 76% in-domain. Normalization
  fixes the ordering of staining intensity (normalized "strong" area rises
  0.3% → 0.5% → 2.3% → 14% across BCI 0 → 3+), but most remaining errors are
  2+/3+ cases called 0, which a colour transform cannot fix.
* **Whole-field scoring did not help.** All four quadrants at 2x (`--view
  quad2x`), tried on dev after the first test results to target 3+ cases
  called 0: 45% dev accuracy (QWK 0.43) against 50% for the centre crop, so
  it was not run on test. The whole image at native 20x (`--view full`): 45%.
* **Kappa did not improve** (0.38 → 0.30): normalization fixes many
  adjacent-category errors and introduces some large ones.
* **Labels differ in kind.** Both are case-level scores, not patch-level
  pathologist reads of the exact field the model sees. A 512 px crop of a 3+
  case can contain no stained tumour.
* **One external site.** Two sites show the method transfers once. They do
  not show it generalizes to any third site.
