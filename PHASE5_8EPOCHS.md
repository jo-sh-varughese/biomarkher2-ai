# Phase 5 follow-up: training longer instead of changing the loss

A third lever on moderate (2+), after class weighting (`PHASE5_CLASS_WEIGHTS.md`,
rejected) and the ordinal loss (`PHASE5_ORDINAL.md`, rejected). `PHASE5.md`
noted the baseline run's moderate IoU "was still rising at epoch 4, more
epochs may help further, not yet tested." This is that test.

**Decision rule, fixed in `configs/training_unet_8epochs.yaml` before the run:**
adopt 8 epochs as the default protocol only if moderate (2+) IoU reaches 0.62
or more (baseline 0.589, plus 0.03 — the smallest gain that clears the ~0.026
single-class run-to-run spread measured between two machines in
`PHASE5_CLASS_WEIGHTS.md`) **and** tissue mean IoU stays within 0.02 of
baseline (0.746, so 0.726 or more).

## What was run

`configs/training_unet_8epochs.yaml` — identical to `configs/training.yaml`
except `optim.epochs: 8` and `output_dir: artifacts/phase2_unet_8epochs`. Same
200 fit / 30 val patches, same seed, same architecture. Trained on the
restored original tile pool (`data/cache/pseudo_labels_40x_orig`, see
`IMPLEMENTATION_NOTES.md`'s "The training pool is whatever tiles are on disk"),
so fit/val are exactly the baseline's 792/119 tiles — the same sample, only
run for twice as many epochs.

The run was interrupted once, by the harness's own memory-pressure protection
(not an error in the run itself — the machine's idle free RAM was already low
for reasons outside this run), partway through epoch 7 at batch 360/396, and
resumed from `resume.pt` with no loss beyond that one un-checkpointed batch
range. Epoch 7's own recorded duration (251s) reflects only the time after the
resume, not the full epoch; every other epoch ran uninterrupted, ~1,660-1,840s
each (~1,675s typical) except epoch 1, which paid a one-time ~700s setup cost
in addition to training. Total: about 3.7 hours of actual compute, spread over
a longer wall-clock window because of the interruption.

## Result

| epoch | background | negative | weak (1+) | **moderate (2+)** | strong (3+) | tissue mean IoU |
|---|---|---|---|---|---|---|
| 1 | 0.8265 | 0.7915 | 0.5103 | 0.0069 | 0.7957 | 0.5261 |
| 2 | 0.8586 | 0.8431 | 0.6495 | 0.4577 | 0.8824 | 0.7082 |
| 3 | 0.8674 | 0.8479 | 0.6636 | 0.6062 | 0.8966 | 0.7536 |
| 4 | 0.8653 | 0.8590 | 0.7411 | 0.5664 | 0.8795 | 0.7615 |
| 5 | 0.8968 | 0.8872 | 0.7207 | 0.6406 | 0.8957 | 0.7860 |
| **6 (selected, best tissue mIoU)** | **0.8960** | **0.8975** | **0.7784** | **0.6569** | **0.9123** | **0.8113** |
| 7 | — | — | — | — | — | 0.8105 |
| 8 | — | — | — | — | — | 0.7945 |

(Only the selected checkpoint's per-class table was written by the training
loop; epochs 7-8's per-class numbers were not kept, only their tissue mean
IoU from `epoch_log.csv`.) Epoch 6 is both the best tissue mIoU and the
checkpoint saved as `best.pt` — epochs 7 and 8 both score lower, so the run
had already started overfitting by the point it stopped, which is itself
useful information: 8 epochs was enough to find the peak, not too few to see
one.

Full before/after, baseline vs. the selected 8-epoch checkpoint:

| class | baseline IoU (`artifacts/phase2_unet`, 4 epochs) | 8-epoch IoU (`artifacts/phase2_unet_8epochs`) | delta |
|---|---|---|---|
| background | 0.861 | 0.896 | +0.035 |
| negative | 0.839 | 0.898 | +0.059 |
| weak (1+) | 0.666 | 0.778 | +0.112 |
| **moderate (2+)** | **0.589** | **0.657** | **+0.068** |
| strong (3+) | 0.891 | 0.912 | +0.021 |
| tissue mean IoU | 0.746 | 0.811 | +0.065 |
| pixel accuracy | 0.908 | 0.938 | +0.030 |

## Decision

**Adopt.** Moderate clears the +0.03 bar by more than double (+0.068), and
every other class improved too rather than trading accuracy elsewhere — the
"traded some accuracy elsewhere" failure mode that sank both class weighting
and the ordinal loss did not happen here. Unlike those two, this lever did not
change what the model is asked to optimize; it simply let the same objective
run longer, and the baseline's own epoch-4 trajectory (still rising, per
`PHASE5.md`) predicted exactly this outcome.

**Why, most likely:** at 792 fit tiles the model was still underfit at 4
epochs, not at a genuine plateau — the loss curve (`epoch_log.csv`) drops
smoothly through epoch 6 with no sign of the noisy, unstable-loss-landscape
behaviour the class-weighting experiment showed. This is the "cheap lever"
`PROJECT_PLAN.md` §5b called out, and it worked because the earlier
experiments' failure mode (reweighting the same fixed evidence more
aggressively) never applied to it.

## What adopting this means, not yet done

Per the project's own convention (`configs/training.yaml` describes "the"
default protocol, and `artifacts/phase2_unet` is the checkpoint every other
script — the live app, Docker's default `CMD`, both conformal scripts'
default `--config` — points at), fully adopting this result means:

1. Setting `configs/training.yaml`'s `optim.epochs: 4` to `8`.
2. Retraining into `artifacts/phase2_unet` itself (or otherwise repointing the
   app/Docker/conformal defaults at `artifacts/phase2_unet_8epochs`), so the
   checkpoint every other script loads by default is actually the 8-epoch one.

Neither is done yet. Step 1 is a one-line config edit but was deliberately held
back here so the config does not claim to reproduce a checkpoint it does not
yet reproduce (the file at `artifacts/phase2_unet` is still the 4-epoch run).
Step 2 is another multi-hour CPU run, held back for the same reason the
0.42-threshold training run and the full-scale conformal run were: this
session's machine hit its own memory-pressure limit once already, mid-run, and
the next heavy job was deferred to a later session by request rather than run
back-to-back on a machine that had just shown it was short on headroom.

## Note: this uses the config machinery, no new code

Same as `PHASE5_CLASS_WEIGHTS.md`: `training/train.py` already supported an
arbitrary `optim.epochs`. No source code changed for this experiment.
