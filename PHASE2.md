# Phase 2 — Model and training

Status: **complete and runnable. One failure remains and is stated plainly
below — moderate (2+) is still never predicted.** Read "Where it stands" before
reading any metric.

Everything here is a pre-scoring assistive step. Nothing in this phase emits a
HER2 score, and nothing is intended to be read without a pathologist.

Two runs are kept, because the difference between them is the main result of
this phase:

| run | magnification | artifacts | cache |
|---|---|---|---|
| first | ~20× (1024 patch subsampled by 2) | `artifacts/phase2_20x` | `data/cache/pseudo_labels_20x` |
| second | native 40× (1024 patch cut into four 512 tiles) | `artifacts/phase2_40x` | `data/cache/pseudo_labels_40x` |

---

## What was built

| Component | File |
|---|---|
| SegFormer wrapper (logits at input resolution) | `models/segformer_seg.py` |
| Cross-entropy + soft Dice loss | `training/losses.py` |
| Split construction and leakage checks | `training/splits.py` |
| Pseudo-label target cache (tiled) | `training/pseudo_labels.py` |
| Torch dataset + label-safe augmentation | `training/dataset.py` |
| Confusion-matrix metrics | `training/metrics.py` |
| Training loop | `training/train.py` |
| Config (dataclasses + YAML, no Hydra) | `training/config.py`, `configs/training.yaml` |
| Cache builder + target preview | `scripts/build_pseudo_labels.py` |
| Training entry point | `scripts/train_phase2.py` |
| Curves / confusion / per-class plots | `scripts/plot_training.py` |
| Qualitative prediction preview | `scripts/predict_preview.py` |

Tests: `tests/test_splits.py`, `test_losses.py`, `test_model.py`,
`test_metrics.py`, `test_pseudo_labels.py`, `test_train_loop.py`.
154 tests pass, Phase 1 included.

---

## What the model is trained on

**Not annotations.** There are no pixel-level pathologist labels for this
project — not in HER2_IHC_40X, not yet from Kottayam. The dense targets are
**pseudo-labels** produced by thresholding DAB optical density
(`preprocessing/baseline.py`), cached to disk as PNGs so they can be inspected
and disputed rather than assumed. See
`artifacts/phase2_40x/pseudo_label_preview.png`.

The targets pass their sanity check. Mean stained tissue area rises
monotonically with the dataset's own patch label — and it does so identically
at both magnifications, which is how we know retiling changed the resolution
and not the underlying quantity:

| folder label | stained tissue area, 20× cache | 40× cache | mean tissue fraction |
|---|---|---|---|
| 0 | 0.50 % | 0.49 % | 0.453 |
| 1+ | 3.84 % | 3.73 % | 0.589 |
| 2+ | 22.58 % | 21.47 % | 0.709 |
| 3+ | 63.57 % | 62.74 % | 0.787 |

This also settles the open question from Phase 1: the **folder name is the
patch label and the filename prefix is the source slide's overall score**. The
cross-tab of the two over all 10,997 patches is upper-triangular — a patch's
folder score is never *lower* than its slide score — so the two are consistent,
with the folder being the finer-grained of the two.

---

## The split, and a correction made during this phase

The brief requires that patches from one slide never straddle a train/val
boundary. **That cannot be satisfied on this dataset**, and two measurements
say why:

1. **There are no slide identifiers.** Filename suffixes are sparse global
   counters, not slide markers. The coarsest available grouping is
   (slide score × origin) = 8 groups.
2. **Those 8 groups are confounded with the label.** Holding out any one
   removes an entire intensity class from training.

A third measurement changed the design mid-phase. The first version held out
the dataset's `test/` directory. Measuring it killed that idea:

| directory | files named `_train_` | files named `_test_` |
|---|---|---|
| `train/` | 7,345 | 1,452 |
| `test/` | 1,748 | 452 |

78 % of the files in `test/` are named `_train_`. The directories cross the
filename origin token in both directions and carry the same mixture — that is
what a re-shuffle looks like, not a split. Holding out `test/` would have held
out a random sample of the same slides: leakage, dressed as a held-out set.

**So the held-out set is now defined by the filename origin token** (1,904
patches), not by the directory. This is an inference from file naming, not a
verified slide partition, and it is labelled as such in every artifact.

Retiling added the one grouping guarantee this dataset *does* support. Four
tiles cut from one 1024×1024 patch are near-duplicates of each other; if they
straddled fit/validation, validation would be scoring the model on pixels
adjacent to ones it trained on. The cap is therefore applied to **source
patches** and only then expanded to tiles, and `_assert_no_parent_overlap`
checks on every run that no patch has tiles on both sides. That is a weaker
guarantee than slide-level grouping — it is also a real one, enforced by a
test that fails when the guard is broken.

Both caveats — `VAL_LEAKAGE_CAVEAT` and `HOLDOUT_CAVEAT` — are written into
`split.json`, `run_summary.json`, `best.pt` and every figure, so a number
cannot be lifted out of this directory without them.

**The held-out set was not touched in Phase 2.** It is resolved, counted and
recorded, then left alone. A held-out number watched during development stops
being held out. It is Phase 4's to spend, once.

---

## Run 1 — ~20×, and the failure it exposed

CPU only, 4 threads, no GPU. 500 fit / 120 validation patches, 4 epochs,
~14 min/epoch, MiT-B0, 3.7 M trainable parameters.

Validation, best epoch (epoch 4). **Optimistic — see the caveat above.**

| class | IoU | Dice | precision | recall |
|---|---|---|---|---|
| background | 0.804 | 0.892 | 0.913 | 0.872 |
| negative | 0.751 | 0.858 | 0.813 | 0.908 |
| weak (1+) | 0.030 | 0.059 | 0.414 | 0.032 |
| moderate (2+) | 0.000 | 0.000 | 0.000 | 0.000 |
| strong (3+) | 0.548 | 0.708 | 0.565 | 0.948 |

pixel accuracy 0.809 · mean IoU 0.427 · **tissue mean IoU 0.332**

**The model learned background, negative and strong, and did not learn the two
middle classes.** Pixel accuracy of 0.81 conceals this completely, which is why
model selection is on tissue mean IoU and why the per-class table is the one to
read. The errors were structured, not random: 66 % of weak pixels called
negative, 71 % of moderate pixels called strong — the ordinal middle collapsing
outward to the extremes.

`artifacts/phase2_20x/prediction_preview.png` showed the mechanism, and it was
not mainly class imbalance: **the predictions were smooth blobs where the
targets are thin membrane lace.**

The diagnosis was a resolution mismatch that is structural rather than a matter
of training longer. SegFormer's decode head predicts at H/4 — 128×128 for a
512×512 input — and the wrapper bilinearly upsamples 4× to full size. At 20× a
membrane rim is 1–3 pixels wide and therefore **sub-pixel at the resolution the
model actually predicts at**. It cannot represent the structure the targets are
made of. Large confluent 3+ regions survive because they are big enough; weak
and moderate rims cannot.

---

## Run 2 — native 40×

The fix follows directly from the diagnosis. Rather than subsampling a 1024×1024
patch by 2 to make one 512 tile, cut it into four 512 tiles at native
resolution (`configs/preprocessing.yaml`, `tiling.downsample: 1`). Every
membrane is twice as wide in pixels **at identical compute cost** — the model
still sees 512×512, it just sees a quarter of the field per tile.

Cache: 900 source patches → 3,526 tiles. Run: 200 fit patches (792 tiles), 30
validation patches (119 tiles), 4 epochs, ~21 min/epoch.

Training-target pixel balance over all 792 fit tiles — the shape of the
problem:

| class | share of pixels |
|---|---|
| background | 33.5 % |
| negative | 47.3 % |
| weak (1+) | 7.0 % |
| moderate (2+) | 3.6 % |
| strong (3+) | 8.6 % |

Validation across epochs (**optimistic — see the caveat above**):

| epoch | train loss | val loss | pixel acc | tissue mIoU | weak (1+) IoU |
|---|---|---|---|---|---|
| 1 | 1.516 | 0.931 | 0.815 | 0.340 | 0.064 |
| 2 | 1.072 | 0.773 | 0.849 | 0.403 | 0.211 |
| 3 | 0.970 | 0.744 | 0.845 | 0.419 | 0.282 |
| 4 | 0.923 | 0.722 | 0.862 | **0.443** | **0.341** |

Best epoch (4), per class:

| class | support | IoU | Dice | precision | recall |
|---|---|---|---|---|---|
| background | 11,948,196 | 0.852 | 0.920 | 0.892 | 0.949 |
| negative | 14,390,469 | 0.815 | 0.898 | 0.927 | 0.871 |
| weak (1+) | 1,602,217 | 0.341 | 0.508 | 0.555 | 0.469 |
| moderate (2+) | 899,868 | 0.0001 | 0.0001 | 0.209 | 0.0001 |
| strong (3+) | 2,354,386 | 0.618 | 0.764 | 0.630 | 0.968 |

pixel accuracy 0.862 · mean IoU 0.525 · **tissue mean IoU 0.443**

Losses fell monotonically and validation tracked training throughout — nothing
diverged, nothing overfit (`artifacts/phase2_40x/training_curves.png`).

### 20× vs 40×

| metric | 20× | 40× | change |
|---|---|---|---|
| tissue mean IoU | 0.332 | 0.443 | +33 % |
| weak (1+) IoU | 0.030 | 0.341 | ×11 |
| strong (3+) IoU | 0.548 | 0.618 | +13 % |
| negative IoU | 0.751 | 0.815 | +9 % |
| moderate (2+) IoU | 0.000 | 0.0001 | unchanged |

**Epoch 1 at 40× already beat the entire 20× run** (tissue mIoU 0.340 vs 0.332),
on 40 % of the source patches. That is the shape of a resolution problem, not a
data-volume or training-length problem, and it confirms the diagnosis above
rather than merely being consistent with it.

---

## Where it stands

**Weak (1+) went from unlearnable to genuinely learned. Moderate (2+) did
not.** It is predicted on 253 pixels out of 21 million — effectively never. The
confusion matrix (`artifacts/phase2_40x/val_confusion_best.png`) shows the
moderate column is empty and the moderate row splits 25.6 % → weak, 70.8 % →
strong.

`artifacts/phase2_40x/prediction_preview.png` shows what is left of the blob
problem. Predictions are much closer to the targets than at 20×, but on 3+
patches the model still paints one confluent strong region where the target is
a lace of strong rims with weak/moderate margins — visible as 27–29 % pixel
disagreement on the two 3+ rows. Moderate is largely a *boundary* class: the
transitional pixels between a strong rim and unstained cytoplasm. It is thin
almost by construction, and it is the last thing the H/4 decode head would
resolve.

Two candidate causes remain, and they are separable by experiment:

- **Still-insufficient resolution.** Moderate rims are thinner than weak ones
  and may remain sub-pixel at H/4 even at 40×. Would be settled by supervising
  at H/4 against a strided target, or adding a full-resolution refinement.
- **Class rarity plus an ordinal neighbour on each side.** At 3.6 % of pixels,
  with weak below and strong above, cross-entropy has little to lose by never
  choosing it. Would be settled by inverse-frequency weights.

**This still matters directly for Phase 3.** The headline output is an *area
percentage*. The 40× model no longer under-paints weak — but it over-paints
strong (recall 0.968, precision 0.630) and assigns essentially nothing to
moderate, so a patch's moderate area would be redistributed into weak and
strong. Phase 3's area percentages built on this model would be biased toward
over-calling HER2 positivity, and the 2+ category — the one that decides who
gets reflex FISH testing — is precisely the one the model cannot express.

---

## Recommended next step (your call)

In order of expected value per hour of CPU:

1. **Inverse-frequency class weights.** Already implemented
   (`training.losses.inverse_frequency_weights`), off by default because on a
   distribution this skewed it can destabilise training. One run answers the
   second hypothesis above. Cheapest decisive experiment.
2. **Supervise at H/4 against a strided target**, or add a full-resolution
   refinement to the decode head. Answers the first hypothesis, and makes the
   metrics honest about the resolution the model actually predicts at.
3. **More data and more epochs.** 200 of ~7,700 available fit patches were
   used, for 4 epochs. Worth doing once the above two are resolved — not
   before, or it just buys a more expensive version of the same failure.
4. **Reconsider the threshold cut points.** `dab_od_moderate: 0.50` and
   `dab_od_strong: 0.80` are provisional Phase 1 numbers. If moderate is a thin
   transitional band by construction, the cut points — not the model — may be
   what needs review, and that is a question for the pathologist rather than
   for a hyperparameter sweep.

I have not run any of these unasked — the Phase 2 gate is yours.

---

## Standing concerns carried forward

1. **Circularity.** The model is trained on DAB thresholds. Agreement with
   those thresholds proves nothing. `preprocessing/baseline.py` must be carried
   through Phase 4 as an experimental control; if SegFormer does not beat the
   classical thresholder, the honest finding is that it adds nothing.
2. **Intensity-only segmentation is a real simplification of CAP.** CAP depends
   on membrane *completeness* and circumferential pattern, not intensity alone.
   Phase 3's report must say so plainly.
3. **The denominator is not CAP's denominator.** These are percentages of
   *tissue area*; CAP's are percentages of *tumour cells*. They diverge whenever
   stroma content varies, and it varies enormously here (tissue fraction 0.45 →
   0.79 across classes). Phase 3 must label the number as tissue-area
   percentage, not cell percentage.
4. **No slide identity, therefore no defensible generalization estimate.** The
   held-out set is the best approximation this dataset supports and no more.
   Only the Kottayam slides can fix this.

---

## Reproducing

```
python scripts/build_pseudo_labels.py --limit 900 --preview 8
python scripts/train_phase2.py --config configs/training.yaml
python scripts/plot_training.py --run artifacts/phase2_40x
python scripts/predict_preview.py --run artifacts/phase2_40x --count 8
pytest -q
```

`configs/preprocessing.yaml` controls the magnification: `tiling.downsample: 1`
reproduces run 2, `2` reproduces run 1. `configs/training.yaml` must point
`data.cache_root` at a cache built with the matching setting.
