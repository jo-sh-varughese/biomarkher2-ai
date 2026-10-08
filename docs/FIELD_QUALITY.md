# Field-quality gate (app/field_quality.py)

Before 2026-10-08 the analysis always returned a grade. A probe of the real pipeline showed:

| Input | Old output |
|---|---|
| Blank glass (0% tissue) | 2+, "ISH required" |
| Black frame | 3+ |
| Random noise | 3+ |
| H&E-like image | 2+, "ISH required" |
| Uniform brown fill | crash (`threshold_multiotsu`) |
| Greyscale copy of a 3+ field | 0, "ISH not indicated" |
| 3+ field, 90% glass / over-exposed | 0 / 2+ |

Now every field passes a gate first. A field that fails any **blocking** check is
reported as **Not assessable**, with its reasons and what to do: no AI pre-score
(the model is not even run), no cell category, no ISH suggestion, and the review
form starts at "cannot assess". **Caution** checks keep the grade and add a caution.

## Checks

| Code | Level | Test |
|---|---|---|
| `too_small` | block | shorter side < 256 px |
| `too_dark` | block | > 50% of pixels near-black |
| `noise` | block | mean neighbour difference of luminance > 40 |
| `graphics` | block / caution | > 25% / > 5% of stained area in perfectly flat 8x8 blocks |
| `greyscale` | block | mean channel spread over stained pixels < 2 |
| `no_structure` | block | luminance s.d. in tissue < 3 |
| `not_ihc` | block / caution | eosin share of stain > 0.05 / > 0.03 |
| `marker` | block / caution | > 10% / > 0.5% of stained area in green/cyan marker colour (excluded) |
| `dark_deposits` | caution | > 1% near-black neutral deposit: ink, pigment, fold (excluded) |
| `nuclear_stain` | block / caution | > 30% / > 20% of DAB in filled round nucleus-sized blobs (ER/PR/Ki-67 pattern) |
| `little_tissue` | block / caution | tissue < 5% / < 20% of frame |
| `few_cells` | block / caution | < 30 / < 100 cells measured |
| `out_of_focus` | block / caution | Laplacian variance < 0.00012 / < 0.0002 |
| `edge_artefact` | caution | > 50% of strong DAB in the outer tissue rim |
| `excluded` | caution | >= 0.5% of tissue removed as artefact |
| `not_breast` | block | tumour site is not breast (gastric HER2 rules differ) |

Uploads are decoded by `app/image_io.py`: corrupt/empty files give a clear 400,
images over 64 megapixels are refused before decoding, 16-bit images are rescaled,
transparency becomes glass, CMYK/palette are converted, EXIF rotation is applied,
and multi-page TIFFs use page 1 with a note. At most two analyses run at once
(`BIOMARK_ANALYSIS_SLOTS`); further requests queue.

Whole slides: each field is measured; fields failing a stain/graphics/marker check
or out of focus are dropped (listed in `rejected_fields`). If most fields are H&E or a
nuclear stain, or none is usable, the slide is Not assessable. On a slide scanned
below ~20x the focus check is skipped (upsampled fields always look soft) and the
existing magnification rule governs.

Review record (`app/review_record.py`): a final 0-3+ score is refused when the tumour
site is not breast, the control is unacceptable, the field is marked as having no
invasive tumour, or when a negative (0/1+) is signed on tissue marked poorly fixed,
ischaemic or decalcified (ASCO/CAP: false-negative risk; retest).

## Calibration (scripts/calibrate_field_quality.py, artifacts/field_quality_calibration.json)

| Group | n | Must | Result |
|---|---|---|---|
| HER2-IHC-40x held-out fields, all grades | 120-150 | pass | 0 blocked |
| BCI fields (second site, grey glass) | 80-120 | pass | 0 blocked |
| Fields of a real HER2 whole slide | 12 | pass | 0 blocked |
| Fields of a real H&E whole slide | 12 | fail | 12/12 `not_ihc` (eosin 0.057-0.28; HER2 max 0.009) |
| Ki-67 (BCData) nuclear IHC | 80 | fail | 64% blocked, 84% blocked or cautioned |

Edge-artefact caution fires on 1.5% of real HER2 fields.

## What the gate cannot do (stated, not hidden)

* **Brown pigment vs DAB** (melanin, haemosiderin): same colour. Only very dark deposits
  are caught; the pathologist must exclude pigment (review artefact option provided).
* **DCIS, normal ducts, necrosis, crush, folds, tumour-free fields, control cores in a single
  field**: not recognised from the image. The tool does not segment tumour; the review form
  records these and refuses a score for a field marked as having no invasive tumour.
* **Fixation, cold ischaemia, decalcification**: invisible in the image; enforced through
  the review record rules above.
* **Magnification of a single uploaded field**: a PNG carries no microns-per-pixel. Very
  low-power images fail on cells/structure; whole slides use the scanner's value.
* **Ki-67 with few positive nuclei** looks like a HER2 0 field; about a third are not caught.
* **The same field re-encoded** (e.g. PNG -> JPEG) gets a different case id, because the id
  is a hash of the pixels.
