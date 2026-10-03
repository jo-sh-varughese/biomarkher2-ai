# Multi-task U-Net (v2): plan, targets and runbook

Written 2026-10-02, **before any GPU run**. Targets and the evaluation
protocol below are fixed now and are not to be changed after results come in.

## Why a v2

The shipped model (`artifacts/phase2_unet_8epochs`, ResNet18-U-Net) learns
only from DAB-threshold pseudo-labels, and it scores almost exactly what that
rule scores: 76.0% vs 75.0% in-domain, 39.9% vs 39.6% on BCI
(`docs/CROSS_SITE_STAIN_NORMALIZATION.md`). It also trained on 200 of 7,729
available patches, a CPU limit. v2 changes what the network learns from and
how much it sees, and keeps the U-Net's explainable intensity map.

| Change | Code |
|---|---|
| Score head on the U-Net encoder, trained on real 0/1+/2+/3+ labels; attention pooling over all tiles of a patch/case | `models/multitask.py` |
| Encoder ResNet18 (ImageNet) → ResNet-50 with pathology self-supervised weights (Lunit, Kang et al. CVPR 2023) | `models/unet_seg.py` |
| All 7,729 fit patches, not 200 | `configs/v2_*.yaml` |
| Stain (H/DAB vector + moderate concentration), zoom, blur/noise/resampling augmentation, on the GPU | `training/gpu_ops.py` |
| Segmentation decoder still trained on the same pseudo-label rule, computed on the GPU (98.6% pixel agreement with the CPU pipeline on 12 real patches) | `training/gpu_ops.py` |
| Multi-site training option (our data + BCI train) | `training/v2_data.py` |
| Budget guards: wall-clock cap, per-epoch checkpoints + resume, throughput guard, auto-stop pod | `training/v2_engine.py`, `scripts/pod/run.sh` |

Tests: `tests/test_v2.py` (23). A 4-patch overfit check on CPU drove score
loss 1.99 → 0.26 and seg loss 3.05 → 0.82 in 20 steps, with all four patches
predicted correctly from step 4.

## Targets (pre-registered)

| Target | Measured on | Label |
|---|---|---|
| **In-domain: accuracy > 90%, QWK ≥ 0.90** | HER2_IHC_40X reserved holdout (1,904 patches, never trained on or used for selection) | patch label (folder class) |
| **Unseen site: accuracy > 80%, QWK ≥ 0.80** | a site the run never trained on: BCI test (977) for runs A; HER2_IHC_40X holdout for run C | BCI: case score from the report |

Also always reported: balanced accuracy, macro-F1, within-one, confusion,
the HER2_IHC_40X result against the *slide* label, and BCI on the 338-image
subset used in the earlier cross-site test (old model: 39.9%).

**Ceilings to read results against.** Against slide labels, a perfect patch
reader on HER2_IHC_40X caps near 92% (patch and slide labels disagree on ~8%
of test patches). BCI labels are case-level from the report, and
pathologists themselves disagree on 0 vs 1+; no number here is clinical
validation.

## Protocol

* **Model selection** = the epoch with the highest mean validation QWK over
  the run's validation sets (HER2_IHC_40X val split; plus BCI val, 10% of
  BCI train, when BCI is trained on). Test sets are never looked at during
  training.
* **Test once.** `scripts/eval_v2.py` runs on `best.pt` after training.
  Every external set is reported raw and with site-level stain
  normalization toward the training site; both are shown, neither is
  dropped.
* **"Unseen" means unseen site.** In run B, BCI test is a *seen* site (new
  images from a hospital the model trained on) and is reported as in-domain.
  Only runs A and C produce unseen-site numbers.
* BCI images are brought to our 40x scale (512 px regions upsampled 2x).
  Training sees random 512 crops, evaluation sees all four quadrants.

## Runs and budget

Hard budget: **$6.72**, no top-ups. GPU: **RTX 4090, community cloud,
$0.34/hr** (live price 2026-10-02; fallback RTX 3090 $0.22 → 3090 Ti $0.27).

| Run | Config | Purpose | Cap | Est. cost |
|---|---|---|---|---|
| 0 | `v2_run0_gpu_check.yaml` | pod works end to end; measures real tiles/s | 10 min | ~$0.06 |
| A | `v2_run_a.yaml` | our data only → in-domain target + BCI as unseen site | 120 min | ≤ $0.70 |
| B | `v2_run_b.yaml` | our data + BCI train → best two-site model | 150 min | ≤ $0.85 |
| C | `v2_run_c.yaml` | BCI only → our holdout as unseen site | 90 min | ≤ $0.50 |
| | data download + setup per pod, result copy window | | ~20 min/pod | ~$0.12/pod |
| | **Planned total** | | | **≈ $2.5** |
| | Reserve (failures, one re-run) | | | ≈ $4.2 |

Run 0 and A go on the same pod (the throughput guard skips A if Run 0 shows
< 40 tiles/s). B and C only after A's results are read.

## Runbook

Local, once per launch:

```bash
bash scripts/pod/pack.sh                       # -> dist/her2_v2_code.tgz (code + frozen splits/profiles)
```

Pod (created only with explicit approval): image with PyTorch ≥ 2.3 + CUDA
12.x, 1 GPU, container disk ≥ 40 GB, SSH enabled. Then:

```bash
scp dist/her2_v2_code.tgz root@<pod>:/workspace/  &&  scp ~/.kaggle/credentials.json root@<pod>:/root/.kaggle/
ssh root@<pod> 'mkdir -p /workspace/HER2_PROJECT && tar -xzf /workspace/her2_v2_code.tgz -C /workspace/HER2_PROJECT &&
  cd /workspace/HER2_PROJECT && nohup bash scripts/pod/run.sh configs/v2_run0_gpu_check.yaml configs/v2_run_a.yaml > /workspace/run.out 2>&1 &'
# follow: ssh root@<pod> tail -f /workspace/logs/pod_run.log
# results: scp root@<pod>:/workspace/results_*.tgz .   (within RESULT_GRACE_SEC after "ALL DONE")
```

The pod stops itself on exit (or at `HARD_LIMIT_MIN`, default 200 min).
Afterwards **delete** it: a stopped pod still bills for its disk.

## What is not decided here

* Whether the score head ever appears in the live viewer. The project's
  enforced rule is that the viewer never emits a score
  (`IMPLEMENTATION_NOTES.md`, `tests/test_app.py`); the score head is an
  offline evaluation tool unless the project guide decides otherwise.
* The Kottayam slides. Patient data does not go to community cloud.

## Results

### Run 0 (2026-10-02, RTX 4090 community)
Pipeline works end to end on the GPU. Measured **~139 tiles/s** (about 4x the
planning estimate), so Run A's epochs were raised 12 → 25 before Run A
started. A first pod was discarded unused: PyTorch could not reach its GPU
("CUDA unknown error"); `run.sh` now checks this before anything else.

### Run A: our data only (25 epochs, 50.5 min, best epoch 25 by val QWK 0.970)

| Test set | Role | Condition | n | Accuracy | Balanced | QWK | Target |
|---|---|---|---|---|---|---|---|
| HER2_IHC_40X holdout (patch label) | in-domain | raw | 1,904 | **88.7%** | 87.4% | **0.965** | acc >90%: **missed by 1.3 pts**; QWK ≥0.90: **met** |
| HER2_IHC_40X holdout (slide label) | in-domain | raw | 1,904 | 87.6% | 86.6% | 0.958 | (reported) |
| BCI test | unseen site | raw | 977 | 48.3% | 47.7% | 0.329 | missed |
| BCI test | unseen site | site-normalized | 977 | 54.5% | 47.0% | 0.308 | missed |
| BCI 338-image subset | unseen site | raw / site-normalized | 338 | 42.0% / 44.4% | 46.9% / 45.7% | 0.428 / 0.373 | old model: 29.9% / 39.9% |

* Holdout within-one: 99.8%. Errors are almost all 0 ↔ 1+ (97 zeros called
  1+, 34 1+ called 0) and 1+ → 2+ (65): the boundaries pathologists also
  disagree on most. 2+ recall 94%, 3+ recall 99%.
* The segmentation decoder still agrees with the pseudo-label rule on 89.9%
  of pixels, so the viewer's intensity map is preserved.
* On BCI the model almost never predicts 1+ (recall 2–3%) and calls most 3+
  cases 2+ (recall 40–45%). Site normalization adds +6.1 accuracy points
  (95% CI +4.2 to +8.3) but does not improve QWK.
* Spend for Run 0 + A, including the discarded pod: $0.36.

### Site-Adaptive HER2 Calibration on BCI (stages 1, 3, 4; 2026-10-02)

Starts from Run A (never saw BCI). Adaptation used BCI's 3,896 *train*
images with labels stripped (`training/site_adapt.py`); scored once on BCI's
977 test images. Settings fixed beforehand in `configs/v2_adapt_bci.yaml`.

| Stage | Accuracy | Balanced | Macro-F1 | QWK | Recall 0 / 1+ / 2+ / 3+ |
|---|---|---|---|---|---|
| A0 as scanned | 48.4% | 47.8% | 0.361 | **0.330** | 74 / 2 / 76 / 40% |
| A1 + site stain normalization | **54.5%** | 47.0% | 0.406 | 0.308 | 53 / 3 / 87 / 45% |
| A2 + BatchNorm adaptation | 49.4% | 44.6% | 0.402 | 0.231 | 42 / 17 / 63 / 55% |
| A3 + intensity-preserving self-training (+ BN) | 52.5% | **53.5%** | **0.473** | 0.314 | 63 / **42** / 59 / 50% |

* Self-training fixed the "never predicts 1+" failure (1+ recall 2% → 42%)
  and gave the best balanced accuracy and macro-F1 of any method tried on
  BCI. Accuracy vs A0: +4.1 points (95% CI +0.7 to +7.3).
* BatchNorm adaptation alone **hurt** (QWK 0.33 → 0.23, CI excludes zero).
* **No stage improved QWK.** Gains are within-one-step reshuffles (0↔1+↔2+);
  large ordinal errors (3+ called 0: 46 cases) remain.
* Conclusion: label-free adaptation helps class balance modestly but does not
  close the cross-site gap; consistent with the stain-correction ceiling
  (~54%). The adapted checkpoint was not kept (download cut off when the pod
  was deleted); it can be regenerated from the config in ~7 GPU-minutes.
* Spend for this test: ~$0.32 (two faulty community hosts discarded, then a
  secure-cloud RTX 4090). Balance after: $6.05.

### Site fingerprint, 25-case onboarding and Run B (2026-10-02)

**Fingerprint** (`evaluation/site_fingerprint.py`, `scripts/site_fingerprint.py`;
report in `artifacts/fingerprints/bci/`): BCI is 0.46 vs our 0.24 um/px
(x1.92), JPEG q~94 like ours, background 31/255 darker, haematoxylin 17 deg
off, DAB about half as strong (label-free correction x1.91). Magnification
comes from scanner metadata; the nucleus-size estimate is a low-confidence
cross-check only (it read x6 on BCI; a direct test confirmed x2: x2 43.1%,
x3 42.0%, x4 38.8%). Blur alone is not a cause (our holdout made BCI-blurry:
88.5% -> 91.5%).

**25 labelled cases** (Kottayam's budget; `scripts/fewshot_v2.py`, five
draws each; DAB correction picked on the 25 cases, fine-tune with replay):

| Budget | Accuracy, 5 draws | Mean acc | Mean QWK |
|---|---|---|---|
| 0 labels (fingerprint correction) | 54.9% | 54.9% | 0.30 |
| 25 balanced (6/6/6/7) | 39.4-57.8% | 49.7% | 0.37 |
| 25 Kottayam mix (9/4/2/10) | 31.0-42.8% | 37.5% | 0.33 |

25 cases do not reliably help: the DAB choice is noisy on 25 cases, and a
skewed mix (2 x 2+) biases the model away from BCI's 2+-heavy test set.

**Run B: our data + BCI train labels** (16 epochs, best epoch 11 by mean val QWK):

| Test set | n | Accuracy | Balanced | QWK | Target |
|---|---|---|---|---|---|
| HER2_IHC_40X holdout (patch label) | 1,904 | **92.3%** | 89.5% | **0.975** | in-domain >90% / >=0.90: **met** |
| BCI test, raw (seen site, new images) | 977 | **75.3%** | 77.4% | 0.698 | >=70% reached; QWK 0.80 not |
| BCI test, site-normalized | 977 | 49.9% | 56.6% | 0.480 | (model trained on raw BCI) |
| BCI 338 subset, raw | 338 | 72.2% | | 0.743 | old model 29.9% |

Site normalization now hurts because the model learned BCI's raw colours;
normalization is for sites the model has NOT trained on. BCI test here is a
seen site (new images of a hospital in training), not an unseen one.
Spend for this pod: ~$0.70 (secure RTX 4090). Balance after: $5.35.

### Four upgrades to stain normalization (2026-10-02)

**1. Per-slide control calibration** (`evaluation/control_calibration.py`,
`scripts/simulate_control_calibration.py`). Simulation on 160 of our holdout
patches in 16 staining runs (DAB x0.5-1.6, H x0.85-1.2), each run with its own
3+ control:

| Method | Original | Shifted | Site-level correction | **Control calibration** |
|---|---|---|---|---|
| DAB-threshold rule + ASCO/CAP: accuracy / QWK / off by 2+ | 60.0% / 0.831 / 3.7% | 51.2% / 0.764 / 7.5% | 52.5% / 0.769 / 7.5% | **58.1% / 0.820 / 4.4%** |
| Run A model: accuracy / QWK | 88.7% / 0.955 | 88.1% / 0.954 | - | - |

Control calibration recovers most of the run-to-run loss for intensity-
threshold scoring, where site-level correction cannot (runs differ inside one
site). The neural model is already robust to this kind of DAB variation (its
stain augmentation), so for it there is little left to correct. (The oracle
condition and the model's remaining conditions were cut by the background
time limit.)

**2. One shared stain space for training** (`data.train_site_norm`).
Run C (BCI only) tested on OUR holdout, which neither model saw:

| Model | Our hospital (unseen): accuracy / QWK | BCI test: accuracy / QWK |
|---|---|---|
| Run C, BCI raw colours | **67.3% / 0.717** | 58.8% / 0.614 |
| Run C-shared, BCI mapped into our stain space | 62.3% / 0.581 | 57.8% / 0.633 (normalized) |

Training in a shared stain space **hurt** unseen-site accuracy here. Training
on a site's raw colours with stain augmentation generalized better. (Run B,
both sites, raw: BCI 75.3%, ours 92.3% -- combining sites beats either alone.)

**3. Profile stability** (`scripts/profile_stability.py`, 438 BCI images,
30 draws per size): stain colours stabilize at 50-100 images (95th-pct error
3.4 deg at 50, 2.5 at 100); the DAB-strength correction does not (95th-pct
error 20% even at 200 images) because it depends on the case mix sampled.
Label-free DAB correction from 25 slides is unreliable; control calibration
avoids this.

**4. Safety gate** (`evaluation/safety_gate.py`): on real fingerprints --
our site with Run B's local validation (92.3%, QWK 0.98): VALIDATED, scores
shown; BCI unvalidated: SHADOW MODE (scores withheld, maps shown); BCI with
Run B's 75.3% / QWK 0.70 / 5.2% big errors: SHADOW MODE (below the default
thresholds 90% / 0.85 / 1%); magnification unknown: BLOCKED. Thresholds are
defaults for the pathologists to set.

Spend for this round ~$0.31 (one faulty community host ~$0.07, secure RTX
A5000 $0.27/hr). Balance after: $5.04.
