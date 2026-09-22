# Phase 5 — Exploratory Membrane-Completeness Analysis

> **Read §11 before §6 and §7.** Sections 1–10 are the other student's
> original write-up, from their machine. When the analysis was re-run inside
> this repository, the association it reports between completeness and
> moderate IoU turned out to be mostly a bookkeeping effect: about a third of
> tiles contain no moderate class at all, are scored IoU = 0.0, and also
> contain far fewer stained components. Set those tiles aside and the
> association disappears. §11 has the numbers, and what changed in the script.

## 1. Purpose

This experiment prototypes an offline, evaluation-only morphology signal related to HER2 membrane completeness.

The current project uses DAB optical-density thresholds to create pseudo-labels for model training. However, HER2 interpretation is ultimately based on membrane staining around tumour cells, while the current pipeline primarily represents staining at the pixel/tissue-area level.

The goal of this experiment was therefore to test whether a simple connected-component morphology signal derived from the DAB mask is associated with the model's moderate-class behaviour.

This is an exploratory research measurement. It is **not** a clinical HER2 scoring method and was not connected to the live application.

## 2. Scope and constraints

The experiment:

- did not modify `app/`;
- did not modify the existing CAP/conformal evaluation code;
- did not modify the default pseudo-label thresholds;
- did not use virtual staining;
- did not use pathologist annotations, because none are currently available;
- did not evaluate the held-out split;
- used the existing DAB optical-density representation and pseudo-label targets.

The model checkpoint was:

`artifacts/phase2_unet_weighted/best.pt`

The evaluation cache was:

`data/cache/pseudo_labels_050`

The evaluation was performed on the validation split.

## 3. Method

### 3.1 DAB mask

For each cached tile, the existing project DAB optical-density channel was used.

Pixels with DAB optical density at or above:

`DAB_THRESHOLD = 0.25`

were treated as stained pixels for the morphology analysis.

### 3.2 Connected components

An 8-connected component analysis was applied to the stained mask.

Only components with at least:

`MIN_COMPONENT_AREA = 20 pixels`

were retained.

For each retained component, three morphology signals were measured:

1. **Boundary continuity** — how continuously the component boundary is occupied around its centroid.
2. **Ringness** — how strongly the component has a peripheral-ring structure rather than being uniformly filled.
3. **Boundary enrichment** — how strongly DAB signal is concentrated around the component boundary relative to its central region.

These were combined into an exploratory completeness proxy.

The resulting quantity is referred to as a **morphology/membrane-completeness proxy**, rather than clinical membrane completeness.

### 3.3 Model comparison

The weighted U-Net model was run on the same validation tiles.

For each tile, the evaluator recorded:

- number of stained components;
- mean and median morphology completeness;
- mean boundary continuity;
- mean ringness;
- moderate-class target pixels;
- moderate-class predicted pixels;
- moderate-class false positives;
- moderate-class false negatives;
- moderate-class IoU;
- moderate-class false-positive fraction;
- moderate-class false-negative fraction.

Spearman correlation was then used to test whether the morphology measurements were associated with moderate-class model behaviour.

## 4. Synthetic validation

Before running the experiment on project data, the morphology measure was tested on synthetic shapes.

The measured values were:

| Synthetic shape | Continuity | Boundary enrichment | Ringness | Completeness |
|---|---:|---:|---:|---:|
| Complete ring | 1.000 | 0.997 | 0.661 | 0.657 |
| Small gap | 0.889 | 0.989 | 0.692 | 0.602 |
| Large gap | 0.750 | 0.987 | 0.705 | 0.515 |
| Filled disk | 1.000 | 0.500 | 0.154 | 0.000 |

The complete ring produced the highest completeness value, followed by the small-gap and large-gap cases. The filled disk produced zero completeness because its morphology was not ring-like and did not show boundary enrichment.

This provided a basic numerical sanity check before evaluation on project data.

## 5. Validation evaluation

The validation split contained:

- **1,364 source patches**
- **5,349 cached tiles evaluated**
- **1 source patch excluded**

The excluded source patch was:

`train/class_0/her2-0-score_train_3938.png`

Its tissue fraction was approximately **7.00%**, below the existing preprocessing requirement of 10%. It therefore produced no cached evaluation tiles and was excluded rather than forcing it into the experiment.

Of the 5,349 evaluated tiles:

- **3,919** contained at least one sufficiently large stained component;
- **2,319** had a non-zero mean completeness value;
- mean completeness = **0.00484**;
- median completeness = **0.00000**;
- maximum completeness = **0.22604**.

The median of zero shows that the combined morphology signal was sparse across the validation set.

## 6. Association with moderate-class behaviour

### 6.1 Completeness versus moderate IoU

| Measurement | n | Spearman rho | p-value |
|---|---:|---:|---:|
| Completeness vs moderate IoU | 5,349 | 0.383 | 5.57e-186 |
| Ringness vs moderate IoU | 5,349 | 0.167 | 1.07e-34 |
| Boundary continuity vs moderate IoU | 5,349 | 0.668 | <1e-300 |

The combined completeness proxy therefore showed a positive association with moderate-class IoU.

However, boundary continuity alone showed a substantially stronger association than the combined completeness measure.

This suggests that, in this experiment, the continuity component carried more of the relationship with model behaviour than ring-like structure alone.

### 6.2 Association with moderate errors

| Measurement | n | Spearman rho |
|---|---:|---:|
| Completeness vs moderate false-positive fraction | 5,349 | 0.390 |
| Completeness vs moderate false-negative fraction | 5,349 | 0.440 |

The completeness proxy was associated with both false-positive and false-negative fractions.

Therefore, the experiment does **not** support the interpretation that higher morphology completeness simply identifies regions where the model performs better or worse in one specific error direction.

## 7. Interpretation

The experiment produced a measurable morphology signal, but its meaning is exploratory.

The main observations are:

1. The connected-component method behaved sensibly on synthetic examples.
2. The combined completeness proxy was sparse on real validation tiles.
3. The proxy showed a moderate positive association with moderate-class IoU.
4. Boundary continuity had a stronger association with moderate IoU than the combined proxy.
5. Completeness was also positively associated with both moderate false-positive and false-negative fractions.
6. Therefore, the current evidence does not establish that the proxy identifies or corrects moderate-class errors.

The result should consequently be treated as a **research signal for further investigation**, not as evidence of a clinical membrane-scoring capability.

## 8. Limitations

### Pseudo-label targets

The model targets are generated from DAB optical-density thresholds rather than pathologist-labelled cell or membrane annotations.

Therefore, agreement between the morphology signal and model predictions cannot be interpreted as agreement with clinical HER2 membrane assessment.

### Validation split

The existing project validation split is patch-level rather than known slide-level. The HER2_IHC_40X dataset does not provide slide identifiers, so patches originating from the same slide may occur on both sides of the split.

The project already documents this as a validation leakage caveat. These validation measurements are therefore exploratory and should not be treated as independent clinical generalization evidence.

### Morphology proxy

The connected components are derived from a DAB mask and are not explicit tumour-cell or cell-membrane segmentations.

Consequently, a component should not be interpreted as a confirmed individual tumour cell or a clinically defined HER2 membrane.

### No held-out evaluation

The held-out set was deliberately not used. The current experiment was intended as an exploratory validation-split analysis.

## 9. Decision and next steps

Task 3 is considered complete as an exploratory offline experiment.

The result is **not** sufficient to wire the morphology measure into the application or use it for automated HER2 interpretation.

The most useful next research step would be to obtain pathologist-labelled cell-level or membrane-level annotations and evaluate whether the morphology features correspond to clinically meaningful membrane patterns.

A stronger future experiment should also use a verified slide-level holdout so that morphology associations and model performance can be assessed without patch-level leakage.

## 10. Reproducibility

The evaluation was run with:

- checkpoint: `artifacts/phase2_unet_weighted/best.pt`
- cache: `data/cache/pseudo_labels_050`
- split: validation
- DAB threshold: `0.25`
- minimum component area: `20`
- device: CUDA / NVIDIA RTX 4060 Laptop GPU

The experiment produced:

- `artifacts/phase5_membrane_completeness/patch_results.csv`
- `artifacts/phase5_membrane_completeness/summary.json`

The repository test suite completed with:

**299 passed, 1 warning, 0 failures.**

The remaining warning is SciPy's expected `ConstantInputWarning` for the deliberately tested constant-input Spearman correlation case; the evaluator converts the resulting non-finite correlation values to `None`.

(Those paths, the cache and the GPU are the other machine's. §11 says how to
run the merged script in this repository. The warning no longer occurs: the
merged script checks for constant input before calling SciPy.)

## 11. Re-run inside this repository

Added when the handoff was merged into the main repository. Everything in this
section was measured here, on a CPU-only machine, by
`scripts/evaluate_membrane_completeness.py`.

### 11.1 What had to change to run here

As shipped, the script did not run in this repository. It hard-coded
`data/cache/pseudo_labels_050`, a 43,071-tile cache that exists only on the
other machine; against this repository's caches it found no tiles and stopped
with `RuntimeError: No validation tiles were evaluated`. Changes made in the
merge:

- **Arguments instead of constants.** `--run`, `--cache`, `--config`,
  `--max-patches`, `--dab-threshold`, `--min-component-area`, `--output-dir`.
  By default the cache is the one the run was trained on. Output goes to
  `<run>/membrane_completeness/`.
- **Config from `<run>/resolved_config.yaml`, not from inside `best.pt`.** The
  original rebuilt the config from the checkpoint. That works for
  `phase2_unet_weighted` but fails for `phase2_unet`, which was trained under
  an older config schema whose model section still names a SegFormer
  checkpoint (`ValueError: Unknown key(s) for ModelConfig: ['checkpoint']`).
- **Honest accounting of a partial cache.** A cache built with `--limit`
  covers only part of the validation split: here 633 of the 1,364 validation
  patches (2,478 tiles) have tiles in `data/cache/pseudo_labels_40x`. The
  original labelled every patch without tiles "below_min_tissue_fraction",
  which would have been wrong for the other 731. The summary now reports
  `source_patches_without_cached_tiles`, and says the cache does not record
  why a patch has none.
- **`--max-patches`**, applied with `training.splits.stratified_subsample` like
  the other scripts, so a capped run is class-balanced instead of all
  `class_0`.
- **`moderate_present`** per tile, and every correlation reported a second
  time over the moderate-present tiles only (§11.3).

Unchanged: the morphology algorithm, the `0.25` / `20` defaults, the CSV
columns, and the validation-only, holdout-untouched design. The model input is
built as in `training/dataset.py`; on a real tile it is bit-identical to what
`models.prepare_pixel_array` produces (maximum absolute difference 0.0 in both
the normalized input and the logits). §4's synthetic table also reproduces
exactly. The merge added 10 tests to the handoff's 8 (18 in total).

### 11.2 Reproducing

```
python scripts/evaluate_membrane_completeness.py --run artifacts/phase2_unet_weighted --max-patches 200
python scripts/evaluate_membrane_completeness.py --run artifacts/phase2_unet          --max-patches 200
```

Each is about 15 minutes on this CPU (784 tiles at roughly 1.2 s per tile).
Leave out `--max-patches` to use all 2,478 cached validation tiles, about 50
minutes. `phase2_unet` is the adopted baseline; `phase2_unet_weighted` is what
the handoff analysed (that experiment was rejected, see
`PHASE5_CLASS_WEIGHTS.md`).

### 11.3 Results

Both runs below use 784 tiles from 200 validation source patches, spread
evenly over the four folder classes (189 / 198 / 197 / 200 tiles). The handoff
column is as reported in §6, not re-verified.

Spearman ρ over **all** tiles, with the handoff's definition of moderate IoU
(0.0 when the class is absent from both target and prediction):

| | handoff (5,349 tiles) | weighted, here (784) | baseline, here (784) |
|---|---:|---:|---:|
| completeness vs moderate IoU | +0.383 | +0.366 | +0.339 |
| ringness vs moderate IoU | +0.167 | +0.050 (n.s.) | -0.003 (n.s.) |
| boundary continuity vs moderate IoU | +0.668 | +0.616 | +0.599 |
| completeness vs moderate false-positive fraction | +0.390 | +0.404 | +0.376 |
| completeness vs moderate false-negative fraction | +0.440 | +0.479 | +0.438 |

So the handoff's numbers are reproduced in sign and rough size on a different
sample, except ringness, which is not distinguishable from zero here.

The same correlations over only the tiles where moderate exists in the target
or the prediction:

| | weighted (550 tiles) | baseline (523 tiles) |
|---|---:|---:|
| completeness vs moderate IoU | -0.035 (p = 0.41) | -0.156 (p = 3e-4) |
| ringness vs moderate IoU | -0.365 | -0.490 |
| boundary continuity vs moderate IoU | +0.391 | +0.311 |
| completeness vs moderate false-positive fraction | +0.077 | -0.052 (n.s.) |
| completeness vs moderate false-negative fraction | +0.212 | +0.055 (n.s.) |

Why the two tables differ:

| | weighted | baseline |
|---|---:|---:|
| tiles with no moderate in target or prediction | 234 / 784 (29.8%) | 261 / 784 (33.3%) |
| of those, tiles with at least one stained component | 38.9% | 40.6% |
| of the moderate-present tiles, with at least one stained component | 97.5% | 99.6% |
| mean boundary continuity, moderate-absent / moderate-present tiles | 0.220 / 0.621 | 0.223 / 0.640 |

### 11.4 What this changes in §6 and §7

- **The positive association of completeness with moderate IoU (§7, point 3)
  is not supported.** IoU is undefined when a tile has no moderate class in
  either target or prediction, and the evaluator scores it 0.0. Those tiles
  are a third of the sample, and they mostly have no stained structure for the
  morphology measure to find. "This tile has stained components" and "this
  tile has a moderate class" are nearly the same statement, which produces a
  positive correlation on its own. Remove those tiles and completeness vs IoU
  is ρ = -0.035 (weighted) and -0.156 (baseline).
- **Boundary continuity still correlates positively (§7, point 4)**, at
  +0.31 to +0.39 rather than +0.60 to +0.67. This analysis does not control for
  how much stain or moderate area a tile has, and continuity is likely to rise
  with both, so this is not evidence that continuity tracks model quality.
- **Ringness reverses sign** once moderate-absent tiles are set aside (-0.37,
  -0.49). One reading consistent with this is that thin, fragmented stained
  structure is harder to segment than large solid regions; that is a reading
  of the data, not something the analysis tested.
- **The false-positive and false-negative associations (§6.2)** are fractions
  of the tile's area, so they grow with how much moderate-class area a tile
  has, and so does the amount of stain the completeness proxy sees. That is
  what an area effect would look like, and the weak or absent associations in
  the second table point the same way.
- **What stands:** the handoff's own verdict. The measure behaves sensibly on
  synthetic shapes, the signal is sparse on real tiles (median completeness
  about zero), and nothing here supports wiring it into the application or
  treating it as evidence about clinical membrane completeness. Read the
  result as negative for this proxy on these data.

### 11.5 Limits that apply to both sets of numbers

- The moderate target and the completeness proxy are both functions of the same
  DAB channel: the target thresholds it at 0.50 and the proxy at 0.25. Some
  association between them is built in, so it cannot show that the proxy
  captures something the model misses.
- The four tiles of a source patch are near-duplicates and are treated as
  independent here and in §6. The p-values overstate the evidence, most of all
  the very small ones.
- The validation split is patch-level, not slide-level, with the leakage caveat
  in §8. The reserved holdout was not used.
- 784 tiles is a sample: 200 of the 633 cached validation patches.
