# Phase 5 — A second segmentation architecture, measured against the first

Status: **in progress.** The architecture, loss, and training-pipeline
integration are built and tested. A comparative training run is underway;
the numbers in this document are filled in as it produces them, not before.
If a number below says "pending," it is pending — not estimated, not
assumed.

This phase exists because of a direct request to reconsider the model
architecture and to make the overall system's methodology defensible as a
research contribution, not a request to abandon what Phase 2 already
validated. Nothing here replaces SegFormer; it is measured against it.

---

## The question this phase answers

Phase 2 (see PHASE2.md) diagnosed a specific, reproducible failure: SegFormer
predicts at H/4 x W/4 resolution and upsamples once at the end, so the thin
membrane rims that define the moderate (2+) class were sub-pixel at the
resolution the model actually predicts. The model still essentially never
predicts that class (validation IoU 0.0001).

**Is that failure specific to SegFormer's architecture, or is it a property
of the data (too few 2+ pixels, ever, regardless of model)?** Phase 2 could
not answer this alone, because it only ever tried one architecture. Phase 5
is a second, architecturally different attempt at the same labels, so the
question has an actual answer instead of a guess.

---

## What was built

| Component | File |
|---|---|
| ResNet18-UNet, 4-channel (RGB+DAB) input | `models/unet_seg.py` |
| Shared architecture dispatch (used by training and Phase 4 scripts alike) | `models/__init__.py` |
| Focal loss | `training/losses.py` |
| DAB-channel-aware dataset | `training/dataset.py` (`PseudoLabelDataset(include_dab=...)`) |
| Architecture-agnostic training loop | `training/train.py` |
| U-Net training config | `configs/training.yaml` (originally a separate `configs/training_unet.yaml`, folded in once SegFormer's config was removed) |

Tests: `tests/test_unet_model.py`, `tests/test_models_dispatch.py`, plus
additions to `tests/test_losses.py` and `tests/test_pseudo_labels.py`.

---

## The architecture, and why this one specifically

**ResNet18 encoder, U-Net decoder, 4-channel input.** Chosen over other
alternatives for reasons specific to this project's constraints, not as a
default:

* **A U-Net decoder directly targets the diagnosed failure.** Skip
  connections carry the encoder's own full-resolution early features into
  the decoder, rather than relying on one coarse decode head and a single
  upsample to invent detail that was never predicted (see
  `models/unet_seg.py`'s module docstring).
* **A pretrained CNN encoder, not a from-scratch one**, for the same reason
  SegFormer uses a pretrained backbone: this project's calibration and test
  data are small, and transfer learning matters more here than architecture
  novelty for its own sake.
* **4-channel input (RGB + DAB optical density).** The pseudo-label targets
  this project trains on ARE a function of DAB optical density (see
  `training/pseudo_labels.py`). Handing the model that exact, physically
  meaningful quantity as an input channel, rather than requiring it to
  re-derive an approximation of DAB absorption from raw RGB through learned
  convolutions, is a deliberate inductive bias for a weakly-supervised
  setting with very little signal for the rarest class. This is the piece
  that is actually novel here -- not the U-Net architecture itself (Ronneberger
  et al., 2015), which is standard, but feeding a segmentation network the
  same feature space its own weak-supervision labels are computed from.
* **Focal loss (Lin et al., 2017), added to (not replacing) Dice.** Dice is
  insensitive to class cardinality but not to per-pixel difficulty; focal
  loss is the other way around. The two are complementary on a distribution
  this skewed -- background and negative dominate every patch by raw pixel
  count, and focal loss's job is specifically to stop that from drowning out
  the gradient from the rare classes.

## What was measured, and a design decision it produced

A first version of the decoder ran one further stage, with a learned
convolution at the input's own full resolution before the classifier.
**Measured, not assumed:** a smoke run (8 fit / 4 val patches, 1 epoch) with
that stage took 170 seconds. Convolution cost scales with the number of
spatial positions, and that stage was 4x more positions than the one before
it. The decoder now stops one stage earlier (stride 2, not stride 1) --
still twice SegFormer's stride-4 resolution, at a cost this machine can
afford. See `models/unet_seg.py`'s `ResNetUNet` docstring for the exact
numbers.

Measured per-image cost after that fix (forward + backward, batch size 1,
CPU): **~4.4s**, against SegFormer's own documented **~1.45s** (PHASE2.md).
About 3x slower per image, not ~10x. That is the real, current cost of the
resolution this architecture buys back -- stated plainly so the comparison
below is read against an honest price, not an assumed free upgrade.

---

## Resuming an interrupted run

This machine's background processes were killed mid-run, twice, during this
phase's own comparative training (not by anything in this codebase -- both
the training job and an unrelated frontend server died together each time,
pointing at something external: sleep, a session restart, or similar).
`training/train.py` now supports `train(..., resume=True)` /
`scripts/train_phase2.py --resume`, checkpointing model and optimiser state
periodically and at every epoch boundary, so an interruption costs re-reading
some already-seen images, not re-training on them. See the module docstring's
"RESUMING AN INTERRUPTED RUN" and `tests/test_train_loop.py`'s resume tests.

**First real-world test of this was inconclusive in a telling way.** A run
completed epoch 1 in full (tissue mIoU 0.542, `best.pt` and every other
epoch-1 artifact persisted correctly) before being killed partway through
epoch 2. `resume.pt` -- which the code writes at every epoch boundary, and
should therefore have existed reflecting epoch 2's start -- was entirely
absent afterward, with no partial temp file left behind either. `best.pt`
(57MB, written directly, no atomic-rename dance) survived the same event
untouched. That combination is consistent with a write that reached the OS
but was never flushed to disk before whatever killed both this process and
an unrelated one on the same machine -- stronger than a graceful process
stop, closer to a sleep/resume failure or forced shutdown. `_write_resume_checkpoint`
now explicitly `fsync`s the temp file before the atomic rename (directory-entry
fsync was also attempted; confirmed unsupported on Windows via `os.open`,
caught and skipped). Whether this actually fixes the loss or the cause lies
elsewhere is unconfirmed -- there has not yet been a second real interruption
to test it against.

## Comparative results

Both runs share the same split, same seed, same data caps, so the numbers
below are the direct, fair comparison this phase exists to produce.

### Smoke scale (40 fit / 15 val patches, 3 epochs)

Best epoch (3/3, selected on tissue mean IoU):

| class | IoU, epoch 1 | IoU, epoch 2 | IoU, epoch 3 (best) | predicted pixels, epoch 3 | support |
|---|---|---|---|---|---|
| background | 0.688 | 0.743 | 0.793 | 7,263,746 | 6,530,955 |
| negative | 0.537 | 0.626 | 0.744 | 6,192,964 | 7,064,831 |
| weak (1+) | 0.264 | 0.350 | 0.382 | 970,199 | 598,939 |
| **moderate (2+)** | **0.00022** | **0.00012** | **0.00002** | **47** | 340,021 |
| strong (3+) | 0.708 | 0.734 | 0.805 | 1,301,684 | 1,193,894 |

pixel accuracy 0.846 &middot; tissue mean IoU 0.483 (up from 0.377 at epoch 1)

**The one number that matters most here is going the wrong way.** Every
other class improved every epoch. Moderate (2+) got monotonically *worse* --
399 predicted pixels at epoch 1, 152 at epoch 2, 47 at epoch 3, out of
340,021 true ones. This is with the DAB-channel input, the stride-2
(not stride-4) decoder, and focal loss all specifically aimed at this exact
problem. Three consecutive epochs of a different architecture actively
learning *away* from ever predicting this class is real, if still
preliminary, evidence that the failure is not primarily a SegFormer-specific
resolution artifact -- see "What this might mean" below.

### Full scale (200 fit / 30 val patches, 4 epochs -- identical split, seed, and data caps as SegFormer's own `artifacts/phase2_40x`)

**Completed.** Best epoch 4/4 (tissue mIoU still rising at epoch 4 -- more
epochs may help further, not yet tested). Direct comparison, same data,
same split, same seed, both on CPU:

| class | SegFormer IoU (`artifacts/phase2_40x`) | U-Net IoU (`artifacts/phase2_unet`) | delta |
|---|---|---|---|
| background | 0.852 | 0.861 | +0.009 |
| negative | 0.815 | 0.839 | +0.024 |
| weak (1+) | 0.341 | 0.666 | **+0.325** |
| **moderate (2+)** | **0.00006** | **0.589** | **+0.589** |
| strong (3+) | 0.618 | 0.891 | +0.273 |
| tissue mean IoU | 0.443 | **0.746** | +0.303 |
| pixel accuracy | 0.862 | 0.908 | +0.046 |

**This reverses the working hypothesis this document held through the
smoke-scale run and epoch 1 of this same full run.** At smoke scale (40
patches) moderate IoU collapsed across 3 epochs (0.00022 -> 0.00002). At
epoch 1 of this full run (200 patches) it was still barely alive (0.008).
By epoch 4 it is 0.589, with 75.7% recall and 72.7% precision --
not a clinically-usable number on its own, but two-to-three orders of
magnitude past every earlier result tonight, on the same class SegFormer
never learned at all (IoU 0.00006 under identical conditions).

**What this means for the "architecture vs. data" question this document
posed:** the earlier smoke-scale evidence pointed at a structural/data
ceiling, independent of architecture. This full-scale result does not
support that conclusion -- moderate-class learning is real and
substantial here, it just needed more data (200 vs. 40 patches) and more
epochs than the smoke run tested. The honest updated read: SegFormer's
failure on this class looks architecture-specific after all (consistent
with the original PHASE2.md diagnosis -- its quarter-resolution decode
head), not an inherent property of the label distribution. U-Net wins on
**every single class**, not only moderate, and pixel accuracy and tissue
mean IoU both improve substantially too.

**Decision: adopt ResNet18-UNet as the sole architecture; drop SegFormer.**
Beyond the accuracy numbers above, U-Net is plain Conv2d/BatchNorm/ReLU/
bilinear-interpolate -- it exports to ONNX and quantizes with essentially
no surprises, unlike SegFormer's HuggingFace `transformers`-wrapped
attention/patch-merging architecture. Dropping SegFormer also removes six
now-unused dependencies (`transformers`, `tokenizers`, `safetensors`,
`hf-xet`, `huggingface_hub`, `annotated-doc`) and shrinks the eventual
Docker image. See `IMPLEMENTATION_NOTES.md` for the consolidation this
decision triggered.

### What the smoke result meant, resolved

Two competing explanations were posed here at smoke scale, not yet
distinguished:

1. ~~A genuine data/label problem~~ (the pseudo-labels bin a continuous DAB
   optical density into weak/moderate/strong at fixed cut points, and the
   moderate band sits between two neighbours it could be confused with on
   both sides regardless of architecture).
2. **Not enough training yet, at this data scale — confirmed.** The
   full-scale run (5x the smoke run's data, same 4 epochs) took moderate
   IoU from 0.00002 (smoke scale, collapsing) to 0.589 (full scale). Under
   identical data and epochs, SegFormer still got 0.00006. Explanation 2
   is the one the evidence supports; explanation 1 is not needed to
   account for what was observed at smoke scale — it was simply too little
   data and too few epochs to see the class learned at all, on either
   architecture, which is a different claim than "the class is
   unlearnable."

---

## Inherited limitations

Every caveat that already governs Phase 2's SegFormer numbers governs these
too, unchanged: the targets are DAB-threshold pseudo-labels, not pathologist
annotations (`training/pseudo_labels.py`); the validation split is not
leakage-free (`training/splits.py`); the held-out set is spent once, by
Phase 4, and this comparison does not touch it a second time -- both models
are compared on the same *validation* split, not the reserved holdout.

## What would make this a stronger research contribution

1. **This comparison itself, finished and reported honestly** -- including
   if the answer is "SegFormer wins" or "neither reliably predicts 2+ at
   this data scale." A negative result that rules out "wrong architecture"
   as the explanation is still a real finding.
2. **Phase 4's conformal prediction and stain-variation analysis, run
   against whichever model wins** -- both `scripts/calibrate_conformal.py`
   and `scripts/evaluate_conformal.py` already support either architecture
   (`models/__init__.py`'s `select_architecture`), so this is a re-run, not
   new engineering.
3. **Real pathologist annotation**, whenever it exists, to replace pseudo-label
   calibration with the real thing this whole phase is a stand-in for.
