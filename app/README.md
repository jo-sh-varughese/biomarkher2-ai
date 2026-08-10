# Review viewer

A local web viewer for the Phase 2 model, meant to be shown to a pathologist
and demonstrated in a presentation.

```
python -m app.server --run artifacts/phase2_40x
```

Then open <http://127.0.0.1:8000>. Standard library only — no Flask, no
FastAPI, no CDN, nothing fetched from the internet at runtime.

## What it does

Pick an example patch from the dataset or upload an IHC image, and it runs
Phase 1 preprocessing and the Phase 2 model over it, then shows four panels
and one table:

| panel | what it is |
|---|---|
| Original field | as scanned |
| Detected tissue | the mask that is the denominator of every percentage |
| Model intensity map | SegFormer's per-pixel classification |
| Threshold baseline | the classical DAB rule the model was trained to imitate |

The table gives stained area per intensity class as a percentage of detected
tissue — **model and baseline side by side, always**.

## Three things it does deliberately

**It never shows a HER2 score.** Not in the UI, not in the JSON. `tests/test_app.py`
asserts the payload contains no `score` / `verdict` / `diagnosis` field, and
that the page says so in words. The score is assigned in step 3, by a person,
and nothing is recorded until they submit it. Their options include "cannot
assess from this field" — a review UI that forces a choice manufactures
agreement it did not earn.

**It shows the baseline every time, not on request.** The model was trained on
DAB-threshold pseudo-labels, so model-baseline agreement is agreement with the
rule it was trained to copy, not evidence of accuracy. A viewer that showed
only the model would hide the one comparison that keeps that honest. The
disagreement percentage is printed under the table.

**It flags the 2+ row in the table itself.** The current model assigns moderate
(2+) to essentially nothing (validation IoU 0.0001). That row is shaded and
annotated inline rather than only footnoted, because a caveat at the foot of
the page is a caveat that gets cropped out of the screenshot. Run a 3+ field
and the failure is visible immediately — on
`test/class_3+/her2-3+-score_train_1120.png` the baseline reports 6.79 % moderate
and 18.97 % strong where the model reports 0.02 % and 38.53 %.

## What it is not

No authentication, no transport security, no real audit trail. It binds to
`127.0.0.1` and warns if you point it elsewhere. It is a local demonstration
and review aid, not a deployable service, and not a medical device.

Percentages are of **tissue area**. CAP/ASCO scoring is defined on the
percentage of **tumour cells** with membrane staining. These are not the same
number and the UI says so.

## Reviews

Confirmations are appended to `artifacts/reviews.jsonl`, one JSON object per
line, each carrying the reviewer, their score, the measurements they were
looking at, a timestamp, and which run produced them. That file is the input
Phase 4 needs for Cohen's kappa — pathologist score against model measurement,
on fields a pathologist actually looked at.

## Options

```
--run            run directory containing best.pt   (default artifacts/phase2_40x)
--config         training config                    (default configs/training.yaml)
--preprocessing  preprocessing config               (default configs/preprocessing.yaml)
--patch-root     dataset root for the examples      (default data/raw)
--reviews        where confirmations are appended   (default artifacts/reviews.jsonl)
--host --port    (default 127.0.0.1:8000)
```
