# Phase 5 follow-up: an auxiliary ordinal-distance loss

A follow-up to `PHASE5_CLASS_WEIGHTS.md`, prompted by that experiment's own
confusion matrix. Decision rule, stated before training, same form as the
class-weighting experiment: **adopt only if moderate (2+) IoU moves
meaningfully upward without a comparable regression elsewhere.**

## Why this was tried

The baseline run's confusion matrix (`artifacts/phase2_unet/val_metrics_best.json`)
shows moderate's errors are not spread randomly:

| true moderate pixel predicted as | count | share of moderate's errors |
|---|---|---|
| weak (1+) | 115,740 | 52.9% |
| strong (3+) | 103,069 | 47.1% |
| background / negative | 174 | 0.08% |

Weak's and strong's own errors show the same pattern relative to their own
neighbours. Essentially every misclassification anywhere in this model lands
on the true class's immediate ordinal neighbour. That is the signature of an
ordinal-regression problem being solved with plain multi-class
classification: the five classes are bins of one continuous DAB optical
density (see `preprocessing/baseline.py`), cut at three fixed thresholds, and
cross-entropy/Dice cost a one-class miss the same as a four-class miss.

## What was run

`training/losses.py:ordinal_distance_loss` -- squared distance between the
softmax's expected class index (`sum_c c * p_c`) and the true class index,
added as a fourth term alongside CE + Dice + Focal. No architecture change:
still `NUM_CLASSES` logits, softmax and argmax unchanged everywhere else, so
nothing downstream (inference, conformal prediction, the app) needed to
change. `configs/training_unet_ordinal.yaml`, `ordinal_weight: 0.3`, same
baseline protocol (200 fit / 30 val patches, 4 epochs) otherwise identical to
`configs/training.yaml`.

## An epoch-1 collapse, and what it was

Moderate's IoU was 0.0011 at epoch 1 -- recall was also 0.0011, i.e. the
model almost never predicted moderate as the argmax class at all, worse than
the original baseline's own epoch-1 moderate score (0.008, `PHASE5.md`).

The likely mechanism: `ordinal_distance_loss` penalises the *expectation*
`sum_c c * p_c` being far from the true index. A softmax that splits its mass
roughly evenly between weak (index 2) and strong (index 4) has an
expectation of 3 -- identical to putting all the mass on moderate (index 3)
-- so the loss cannot distinguish "confidently correct" from "hedging
between the two neighbours." Argmax-based IoU can, and it collapsed to
almost nothing under exactly that hedge. This is a real, structural weakness
of expectation-matching ordinal losses, not a training instability.

## It recovered, then settled below baseline

| epoch | moderate IoU | moderate recall |
|---|---|---|
| 1 | 0.0011 | 0.0011 |
| 2 | 0.5002 | 0.5887 |
| 3 | 0.4816 | 0.5328 |
| 4 (selected, best tissue mIoU) | **0.5255** | 0.6352 |

Full final comparison, same validation protocol as `PHASE5_CLASS_WEIGHTS.md`:

| class | baseline (`artifacts/phase2_unet`) | ordinal (`artifacts/phase2_unet_ordinal`) | delta |
|---|---|---|---|
| background | 0.861 | 0.839 | -0.022 |
| negative | 0.839 | 0.804 | -0.035 |
| weak (1+) | 0.666 | **0.722** | **+0.056** |
| **moderate (2+)** | **0.589** | **0.526** | **-0.063** |
| strong (3+) | 0.891 | 0.882 | -0.009 |
| tissue mean IoU | 0.746 | 0.733 | -0.013 |

## Decision

**Reject. Keep `ordinal_weight: 0.0` as the default** (`configs/training.yaml`
unchanged). The hedging collapse fully recovered by epoch 4 -- this is not a
broken loss -- but it settled 0.063 *below* baseline on the class it was
built to help, which fails the stated decision rule regardless of the
recovery story. Weak (1+) is a genuine, non-trivial win (+0.056, and this
run's weak IoU beats even the baseline's own *final* number by epoch 2), and
the regressions elsewhere are smaller than the class-weighting experiment
caused -- so this is a strictly better *general-purpose* loss change than
inverse-frequency weighting was, just not one that fixes the specific
problem it was built for.

**Two experiments, two honest negative results on the target class:**

| class | baseline | class-weighted | ordinal |
|---|---|---|---|
| moderate (2+) | 0.589 | 0.591 (flat) | 0.526 (worse) |
| tissue mean IoU | 0.746 | 0.675 | 0.733 |

## What's next, not tried here

Two cheap, different-hypothesis experiments queued next (see chat/commit
history around this document): training longer (baseline was still rising
at epoch 4 and never plateaued, per `PHASE5.md`) and retraining on the
already-built widened-`dab_od_moderate` pseudo-label cache (the threshold
sensitivity report showed moderate's pixel share is highly sensitive to that
cut point -- this tests whether the label definition itself, not the loss or
model, is the bottleneck). If neither moves it, the next real lever is a
structural one: a true ordinal/cumulative-threshold output head
(CORAL/CORN-style), which by construction cannot hedge between neighbours
the way this expectation-matching loss did -- higher implementation cost,
not attempted in this pass.
