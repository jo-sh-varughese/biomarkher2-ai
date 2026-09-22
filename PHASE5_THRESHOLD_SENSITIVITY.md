# PHASE 5 — DAB Threshold Sensitivity

## Purpose

This experiment tests how changing the DAB optical-density threshold used to separate the weak (1+) and moderate (2+) pseudo-label classes affects the generated training labels.

The original threshold was 0.50. Two alternatives were evaluated:

- 0.42 — lower moderate threshold
- 0.50 — original threshold
- 0.58 — higher moderate threshold

The experiment is intended as a sensitivity analysis of the pseudo-label generation process. It does not establish a clinically correct threshold or replace pathologist review.

## Controlled change

The preprocessing configuration was kept unchanged except for `dab_od_moderate`.

| Variant | Weak threshold | Moderate threshold | Strong threshold |
|---|---:|---:|---:|
| 0.42 | 0.25 | 0.42 | 0.80 |
| 0.50 | 0.25 | 0.50 | 0.80 |
| 0.58 | 0.25 | 0.58 | 0.80 |

Separate cache directories were used so that the threshold variants did not overwrite one another.

## Measured results

The mean class fractions were examined within patches belonging to each source folder class.

### Moderate-folder patches

| Moderate threshold | Negative | Weak | Moderate | Strong |
|---|---:|---:|---:|---:|
| 0.42 | 77.90% | 13.68% | 7.07% | 1.36% |
| 0.50 | 77.36% | 17.07% | 4.22% | 1.34% |
| 0.58 | 77.90% | 18.37% | 2.38% | 1.36% |

The moderate-class fraction increased from 4.22% at the original 0.50 threshold to 7.07% at 0.42, an increase of 2.85 percentage points.

At 0.58, the moderate-class fraction decreased to 2.38%, which is 1.84 percentage points below the original 0.50 setting.

The main change was between the weak and moderate classes, as expected from moving the boundary between them.

### Strong-folder patches

| Moderate threshold | Negative | Weak | Moderate | Strong |
|---|---:|---:|---:|---:|
| 0.42 | 37.56% | 9.80% | 16.78% | 35.85% |
| 0.50 | 37.15% | 13.36% | 12.79% | 36.70% |
| 0.58 | 37.56% | 17.26% | 9.32% | 35.85% |

The same boundary effect is visible in strong-folder patches: lowering the moderate threshold increases the pixels assigned to the moderate class, while raising it moves more pixels into the weak class.

## Stained fraction

The overall stained fraction remained essentially unchanged within each folder class:

- Negative-folder patches: 0.35% at 0.50 versus 0.44% at 0.42 and 0.58.
- Weak-folder patches: 3.58% at 0.50 versus 3.52% at 0.42 and 0.58.
- Moderate-folder patches: 22.64% at 0.50 versus 22.10% at 0.42 and 0.58.
- Strong-folder patches: 62.85% at 0.50 versus 62.44% at 0.42 and 0.58.

This is consistent with the experiment changing the boundary between weak and moderate staining rather than changing which pixels are considered stained overall.

All three variants also passed the preprocessing monotonicity sanity checks.

## Cache-size protocol note

The intended capped preprocessing experiment used `--limit 900`. The generated 0.42 and 0.58 caches nevertheless contain 10,543 patches each, rather than the expected 2,700 total patches from 900 fit + 900 validation + 900 holdout candidates.

The 0.50 control cache was also generated over the full available dataset and contains 43,071 patches.

Therefore, the threshold comparison is reported here as a measured pseudo-label sensitivity analysis over the generated caches, not as a perfectly matched 900-per-split preprocessing experiment. The class-fraction measurements remain useful for understanding the effect of the threshold, but this protocol difference should be considered when interpreting the results.

The downstream training configurations retain the intended controlled limits of 200 fit patches, 30 validation patches, and 200 holdout patches.

## Interpretation

Changing the moderate DAB threshold materially changes how pixels near the weak/moderate boundary are assigned.

The lower threshold of 0.42 produces more moderate-class pixels, while the higher threshold of 0.58 produces fewer moderate-class pixels. The effect is especially visible in patches originating from the moderate and strong folders.

This demonstrates that pseudo-label class balance is sensitive to the selected DAB threshold. However, these measurements alone cannot determine which threshold is more appropriate for HER2 interpretation because the labels are generated from a classical DAB-based heuristic rather than pathologist annotations.

No clinical conclusion is drawn from this experiment.

## Conclusion

Task 2 demonstrates a measurable sensitivity of the pseudo-label distribution to the moderate DAB threshold. The original 0.50 threshold lies between the two tested alternatives, with 0.42 increasing the moderate-class allocation and 0.58 decreasing it.

The experiment supports treating the DAB threshold as an important preprocessing parameter rather than assuming that a single value is universally correct. Future work should compare these alternatives against expert-annotated data before making any clinical interpretation.

No changes were made to `app/`, conformal prediction code, CAP-mapping code, or virtual-staining components.

## Addendum: checked against this repository's caches

Added when this write-up was merged into the main repository. Everything in
this section was computed from `data/cache/*/manifest.csv` and `summary.json`
in this repository, not from the handoff's copies.

**What reproduced.** The 0.42 and 0.58 rows above match
`data/cache/pseudo_labels_40x_moderate_042` and `..._058` to the digit (both
are the same 10,543-tile caches described under "Cache-size protocol note").
The 0.50 row has no counterpart here: it came from a 43,071-tile cache that is
not in this repository. This repository's own 0.50 cache
(`data/cache/pseudo_labels_40x`) has 3,526 tiles, and gives a moderate share of
4.04% in moderate-folder patches and 13.22% in strong-folder patches (against
4.22% and 12.79% above).

**Matched-tile control.** The 3,526 tiles of that cache are a strict subset of
the 10,543-tile variant caches, so all thresholds can be compared on exactly
the same tiles. This repository also has a 0.35 variant that the handoff did
not run. Mean share of tissue per class:

Moderate-folder tiles (n = 889)

| moderate threshold | negative | weak | moderate | strong | stained (1+ and above) |
|---|---:|---:|---:|---:|---:|
| 0.35 | 78.53% | 9.55% | 10.63% | 1.30% | 21.47% |
| 0.42 | 78.53% | 13.36% | 6.81% | 1.30% | 21.47% |
| 0.50 | 78.53% | 16.14% | 4.04% | 1.30% | 21.47% |
| 0.58 | 78.53% | 17.89% | 2.29% | 1.30% | 21.47% |

Strong-folder tiles (n = 900)

| moderate threshold | negative | weak | moderate | strong | stained (1+ and above) |
|---|---:|---:|---:|---:|---:|
| 0.35 | 37.26% | 6.35% | 20.95% | 35.44% | 62.74% |
| 0.42 | 37.26% | 10.13% | 17.17% | 35.44% | 62.74% |
| 0.50 | 37.26% | 14.08% | 13.22% | 35.44% | 62.74% |
| 0.58 | 37.26% | 17.79% | 9.51% | 35.44% | 62.74% |

What this changes:

- Negative, strong and total stained fraction are exactly identical across
  thresholds on matched tiles. The differences the "Stained fraction" section
  reports between its 0.50 row and the two variants (for example 0.35% against
  0.44% in negative-folder patches) therefore come from the different tile
  populations, not from the threshold. That section's conclusion, that the
  threshold moves only the weak/moderate boundary, is right, but its 0.50 row
  cannot be what shows it.
- The moderate-share change against 0.50 on matched tiles is +2.77 / -1.75
  points (moderate folder) and +3.95 / -3.71 (strong folder) for 0.42 / 0.58,
  where the tables above imply +2.85 / -1.84 and +3.99 / -3.47. Same
  direction and size; the tables above carry a population difference in them.
- The moderate share is large in its sensitivity to the cut point. Moving it
  from 0.50 to 0.35 multiplies the moderate-folder moderate share by about 2.6
  (4.04% to 10.63%), so a good part of moderate's thin pixel share is where the
  cut point was put.

**Not done, in either repository.** No model has been trained on any variant
cache. `artifacts/phase2_moderate_*` here holds only a preview image and a
`split.json`, and `configs/training_moderate_*.yaml` have never been run. So
this establishes that the pseudo-label class balance is threshold-sensitive,
not that any threshold improves the model's moderate (2+) IoU, which is step 3
of `tasks/person1_model_quality.md` Task 2. To run that, use
`configs/training_moderate_035.yaml`, `_042.yaml` or `_058.yaml`. The handoff's
`training_threshold_042.yaml` / `_058.yaml` were deliberately not imported:
both set `output_dir: artifacts/phase2_unet`, the baseline run's directory, and
training does not refuse to write into an existing one, so running them would
overwrite the baseline checkpoint that `PHASE5.md` and the conformal
calibration depend on.

## Next step

Task 3 will investigate a different signal: per-cell membrane completeness using an offline classical connected-components analysis of the DAB mask. This will be evaluated against the model's current moderate-class errors as an exploratory analysis.
