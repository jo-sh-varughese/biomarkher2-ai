# Task brief — Evaluation & Infrastructure: finishing Phase 4 at scale

**Give this whole file to your LLM (ChatGPT, Gemini, Claude, whatever you're
using) as context before you start.** It's written to be self-contained —
paste it in, tell your LLM "help me do this in the repo at [path/URL]", and
it should have what it needs.

## What this project is (one paragraph)

BioMarkHER2 is an AI-assisted tool that measures HER2 IHC staining intensity
in breast-cancer biopsy images, to help pathologists score slides 0/1+/2+/3+
more consistently. **It is a pre-scoring assistant a pathologist reviews and
confirms — never an autonomous scorer.** That rule is enforced by actual
tests (`tests/test_app.py`): no code anywhere may produce a field named
`score`, `her2_score`, `verdict`, or `diagnosis`. Don't add one — and in
particular, **never import `evaluation/cap_mapping.py` under `app/`**; it's
deliberately kept offline-only. Full context: `PROJECT_PLAN.md` at the repo
root (read this first) and `IMPLEMENTATION_NOTES.md` for depth.

## Your mission

Phase 4 (`evaluation/`, see `PHASE4.md`) built conformal prediction, stain
variation analysis, CAP/ASCO score mapping, PDF reports, and Docker
packaging. It's software-complete and tested (244+ tests), but two things
were only ever run at a small "does it work" scale, Docker was never actually
verified end to end, and there's no automated testing on push. Your job is
to finish those — mostly compute/verification/infra work, not new algorithms.

**Read before starting:** `PHASE4.md` in full — it states exactly what's
been run at what scale and why, and the caveats every number in this area
carries (calibration is against pseudo-labels, not real pathologist ground
truth — don't accidentally imply otherwise in anything you write).

## Task 1 — Full-scale conformal calibration and evaluation

`training/splits.py` reserves a "holdout" set — ~1,900 patches — explicitly
described as **"Phase 4's to spend, once."** So far it's only been spent at
smoke scale: `scripts/calibrate_conformal.py` and
`scripts/evaluate_conformal.py` were both run with `--max-patches 40`,
producing 157 calibration tiles / 52 test tiles (see `PHASE4.md`'s results
table). A full run over the whole holdout is unrun — expect a multi-hour CPU
job (same order of cost as a full Phase 2 training run).

What to do:
1. Read `evaluation/calibration_split.py` and the two scripts' `--help` to
   understand `--max-patches` (omit it, or set much higher, for a full run —
   check the scripts' argument parsing for the exact flag to use for "no
   cap"; don't just remove the cap without checking what happens to run time
   first — consider running a `--max-patches 200`or `400` intermediate step
   before committing to the full ~1,900).
2. Run `scripts/calibrate_conformal.py` then `scripts/evaluate_conformal.py`
   against the full (or largest-practical) holdout split.
3. Update `PHASE4.md`'s Objective 2 results table with the full-scale
   numbers, replacing (not deleting — keep the smoke-scale numbers for
   comparison, labelled as such) the 40-patch table. Check in particular
   whether miscoverage still tracks alpha as tightly at full scale as it did
   at smoke scale (`PHASE4.md` explains what to look for).
4. If a full run is genuinely impractical on your machine, run the largest
   size that finishes in a reasonable time, say exactly what size and how
   long it took, and note in `PHASE4.md` that the true full-scale run
   remains open — don't round up.

## Task 2 — Verify Docker packaging actually works

`Dockerfile` / `docker-compose.yml` / `.dockerignore` were written and tested
for syntax but **never run** — no Docker was available on the machine that
built them. If you have Docker (Docker Desktop on Windows/Mac, or Docker
Engine on Linux):

1. `docker compose up --build` from the repo root.
2. Confirm: the image builds without error, `torch` installs correctly from
   the CPU wheel index (`Dockerfile` installs it explicitly, separately from
   `requirements.txt` — check this actually happened, don't just assume),
   the container starts, and the viewer is reachable at
   `http://127.0.0.1:8000` from the host.
3. Fix whatever's broken. Common first-run issues to check specifically:
   path/volume mounts for `artifacts/phase2_unet` (the checkpoint needs to be
   inside the container or mounted in), and the port binding matching
   `docker-compose.yml`'s stated `127.0.0.1`-only intent (re-read
   `PHASE4.md`'s Docker section for why that's deliberate — don't "fix" it by
   exposing it more broadly).
4. Update `PHASE4.md`'s Docker section with what you verified (or found
   broken and fixed). If you don't have Docker either, say so plainly in the
   PR rather than skipping this silently — that's still useful information
   for whoever picks it up next.

## Task 3 — Basic CI (GitHub Actions)

There is currently no automated testing on push — tests only run when
someone remembers to run them locally. Add `.github/workflows/tests.yml`:

- Trigger on `push` and `pull_request` against `main`.
- Set up Python 3.11, `pip install -r requirements.txt`, then
  `pip install torch --index-url https://download.pytorch.org/whl/cpu`
  (same two-step install as `CONTRIBUTING.md` — torch is deliberately not in
  `requirements.txt`, see that file's own comment for why).
- Run `pytest -q`.
- Keep it to one job, no matrix needed — this project runs on one Python
  version by design (see `configs/training.yaml`'s CPU-only framing).

Once this exists and is green on your own PR, mention in `CONTRIBUTING.md`'s
step 7 that PRs should wait for it (there's a placeholder sentence there
already referencing "if a CI check is configured" — update it to be
concrete).

## Task 4 (stretch) — stain variation at a larger sample

`scripts/stain_variation_report.py` currently samples 25 patches per
provenance group (200 total). If time allows after Tasks 1–3, rerun at a
larger sample (e.g. 100/group) and update `PHASE4.md`'s Objective 1 numbers,
noting whether `variation_exceeds_noise` and the between/within-group
distances move meaningfully. Re-read `PHASE4.md`'s caveat about these 8
groups being confounded with HER2 score before writing anything up — don't
let a larger sample accidentally get reported as stronger evidence of
cross-*institution* variation than it is.

## Acceptance / how to know you're done

- `pytest -q` still passes in full, including in CI once you've added it.
- `PHASE4.md` is updated with real, dated numbers — not projections — for
  whichever of Tasks 1/2/4 you completed, with the previous smoke-scale
  numbers kept for comparison rather than deleted.
- **You have not built anything related to virtual staining** — out of scope
  for this round.

## Files you'll work in

`evaluation/` (reading, mostly — you're running it, not rewriting the
algorithms), `scripts/calibrate_conformal.py`, `scripts/evaluate_conformal.py`,
`scripts/stain_variation_report.py`, `Dockerfile`, `docker-compose.yml`, new
`.github/workflows/tests.yml`, `PHASE4.md`. See `CONTRIBUTING.md` for the
branch/PR workflow — suggested branch name: `yourname/phase4-full-scale`.
