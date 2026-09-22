# Phase 5 follow-up: inverse-frequency class weighting on U-Net

`tasks/person1_model_quality.md` Task 1. Decision rule stated before looking
at the result, per that task's own instruction: **if moderate (2+) IoU moves
meaningfully upward without a comparable regression elsewhere, adopt
`class_weights: auto` as the new default; if it does not move, or other
classes regress more than it gains, keep `class_weights: null`.**

## What was run

`configs/training_unet_weighted.yaml` — identical to `configs/training.yaml`
(same split, seed, 200 fit / 30 val patches, 4 epochs, same architecture) with
exactly one change: `loss.class_weights: auto` instead of `null`. Trained with
`python scripts/train_phase2.py --config configs/training_unet_weighted.yaml`.

Resolved inverse-frequency weights (`training/train.py:resolve_class_weights`,
computed over all 792 fit tiles):

| class | pixel share | weight |
|---|---|---|
| background | 33.48% | 0.255 |
| negative | 47.32% | 0.180 |
| weak (1+) | 6.95% | 1.227 |
| moderate (2+) | 3.63% | 2.349 |
| strong (3+) | 8.62% | 0.989 |

Per-epoch time: 1679s / 1680s / 1685s / 1667s (≈28 min/epoch, ≈1.86h total) —
in the same range as the baseline run's 2158s/2130s/1735s/1722s (≈2.15h
total); the two aren't meant to be compared for speed (same architecture,
same tile count per epoch, timing varies with machine load), just recorded
for completeness.

## Result

Both runs pick their "best" checkpoint by tissue mean IoU, same criterion,
same validation set methodology (see `PHASE5.md`'s own caveat: validation
patches share a directory with fit, so this is optimistic and used only for
epoch selection, not a leakage-free accuracy claim).

| class | baseline IoU (`artifacts/phase2_unet`) | weighted IoU (`artifacts/phase2_unet_weighted`) | delta |
|---|---|---|---|
| background | 0.861 | 0.810 | **-0.052** |
| negative | 0.839 | 0.734 | **-0.105** |
| weak (1+) | 0.666 | 0.526 | **-0.140** |
| **moderate (2+)** | **0.589** | **0.591** | **+0.002** |
| strong (3+) | 0.891 | 0.850 | **-0.041** |
| tissue mean IoU | 0.746 | 0.675 | -0.071 |
| pixel accuracy | 0.908 | 0.857 | -0.051 |

Moderate's own trajectory across the weighted run's 4 epochs: 0.478 → 0.562
→ **0.600** (epoch 3, this run's peak for this one class) → 0.591 (epoch 4,
the checkpoint actually selected, by tissue mIoU). Even taking the single
best moderate epoch (0.600) rather than the epoch the selection criterion
actually picked, the gain over baseline (0.589) is +0.011 -- well within the
run-to-run noise this data scale (200 fit patches) already showed elsewhere
in this project (see `PHASE5.md`'s smoke-scale-vs-full-scale swings).

## Decision

**Reject. Keep `class_weights: null` as the default** (`configs/training.yaml`
is unchanged). Per the decision rule stated above: moderate did not move
meaningfully in either direction, and every other class regressed, weak
(1+) substantially so (-0.140). This is not a case of "traded some accuracy
elsewhere for a real win on the class that matters" — moderate is flat and
everything else is worse.

**Why, most likely:** inverse-frequency weighting up-weights moderate
2.35x and weak 1.23x while down-weighting background/negative to ~0.18-0.26x.
At this data scale (792 fit tiles, moderate itself only 3.6% of pixels) the
loss landscape shifts enough to destabilize the classes that were already
working well (background, negative, strong) without giving the model enough
signal to actually resolve moderate's harder cases -- it just reweights the
same 792 tiles' worth of evidence, it doesn't add any.

**What might work better, not tried here:** a milder weighting (e.g. capped
inverse-sqrt-frequency instead of raw inverse-frequency, so weights don't
spread as far from 1.0), or the same `class_weights: auto` config on
meaningfully more fit data than 200 patches, since the moderate-specific gain
at epoch 3 (however marginal) suggests the direction isn't obviously wrong,
just underpowered at this scale.

## Independent replication on a second machine

Another student re-ran this exact experiment on their own laptop (handoff
folder `PHASE05_PERSON/`, their own write-up of the same task). Their
`training_unet_weighted.yaml` is functionally identical to ours -- identical
once comments and line endings are stripped. Their checkpoint and logs are not
in this repository, so the numbers below are **as they reported them, not
re-verified here**. (They also had no baseline artifacts, so they compared
against the documented baseline numbers rather than re-training one.)

| class | this run | replication | replication - this run |
|---|---|---|---|
| background | 0.8095 | 0.8219 | +0.012 |
| negative | 0.7339 | 0.7093 | -0.025 |
| weak (1+) | 0.5263 | 0.5526 | +0.026 |
| **moderate (2+)** | **0.5911** | **0.5873** | **-0.004** |
| strong (3+) | 0.8498 | 0.8531 | +0.003 |
| tissue mean IoU | 0.6753 | 0.6756 | +0.000 |
| pixel accuracy | 0.8574 | 0.8553 | -0.002 |

Same decision from both: moderate is flat against baseline (0.5873 there, 0.591
here, versus 0.589) and the other classes are lower. The replication changes
nothing above; what it adds is a direct measurement of this protocol's
run-to-run noise. Moderate agreed to within 0.004 across the two runs, but
individual classes moved by up to 0.026 between them (weak, negative). Their
write-up treats a 0.02 IoU change as "meaningful"; on the evidence of these two
runs alone that is inside the noise for a single class.

## Note: this uses the config machinery, no new code

`training/losses.py` and `training/train.py:resolve_class_weights` were
already built and tested (`tests/test_losses.py`, `tests/test_train_loop.py`)
before this run -- this document is the first time `class_weights: auto` was
actually run to completion on the U-Net architecture, closing that specific
gap named in `PROJECT_PLAN.md` §5b. No source code changed for this task.
