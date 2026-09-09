# Contributing to BioMarkHER2

Read `PROJECT_PLAN.md` first if you haven't — it explains what this project
is and what's left to do. This document is just the mechanics of getting a
change from your machine into `main`.

Two remotes exist, kept in sync:

- **`github`** — `https://github.com/jo-sh-varughese/biomarkher2-ai` (private
  — ask the repo owner to add you as a collaborator before you start; without
  that, `git push` will fail with a permissions error). **Use this one for
  day-to-day work** — branches, Pull Requests, everything below.
- **`origin`** — `https://gitlab.com/her2-final-year-group/biomarkher2-ai`
  (the team's original repo, kept up to date in parallel; GitLab calls the
  same thing a "Merge Request" instead of a "Pull Request" — otherwise the
  workflow below is identical there).

## One-time setup

```
git clone https://github.com/jo-sh-varughese/biomarkher2-ai.git
cd biomarkher2-ai
python -m venv .venv
.venv\Scripts\activate            # Windows;  source .venv/bin/activate on Mac/Linux
pip install -r requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu
pytest -q                         # must show "283 passed" before you touch anything
```

If `pytest` doesn't pass cleanly on a fresh clone, stop and say so rather than
building on top of it — a red baseline makes it impossible to tell your
change broke something from "it was already broken."

## Workflow

1. **Start from an up-to-date `main`.**
   ```
   git checkout main
   git pull github main
   ```

2. **Create a branch.** Name it `<yourname>/<short-topic>`, e.g.
   `priya/moderate-class-weights` or `arun/ci-pipeline`. One branch per task
   from your `tasks/personN_*.md` doc — don't bundle unrelated changes.
   ```
   git checkout -b yourname/short-topic
   ```

3. **Do the work.** Stay inside the files your task doc names as yours where
   you can — the three task docs were deliberately split by directory
   (`training/`+`models/`, `evaluation/`+`scripts/`, `app/`) so three people
   working at once mostly don't touch the same file. If you genuinely need to
   change something outside your area, say so in your PR description.

4. **Run the full test suite before you push, every time:**
   ```
   pytest -q
   ```
   Add tests for whatever you add or change — this project treats tests as
   the actual specification (see `IMPLEMENTATION_NOTES.md`'s "Testing
   philosophy"), not an afterthought. A change with no new test covering it
   is the kind of thing that quietly breaks six weeks later.

5. **Commit** with a message that says *why*, not just *what* — match the
   style already in `git log`: what changed, and the reason, in plain
   language. Small, focused commits beat one giant one.

6. **Push your branch:**
   ```
   git push github yourname/short-topic
   ```

7. **Open a Pull Request** on GitHub, `yourname/short-topic` → `main`.
   Write a short description: what you did, why, and how you verified it
   (which tests, which script output). If a CI check is configured (see
   `tasks/person2_evaluation_infra.md`), wait for it to go green.

8. **Address review feedback** on the same branch — just push more commits,
   the PR updates automatically.

9. **Once approved (and CI is green, if set up): "Squash and merge"** on
   GitHub, so `main`'s history stays one commit per logical change rather
   than every intermediate "wip" commit. Delete the branch afterward (GitHub
   offers a button for this).

10. Back on your machine:
    ```
    git checkout main
    git pull github main
    git branch -d yourname/short-topic
    ```

## Rules that are load-bearing, not style preferences

- **Never add a field named `score`, `her2_score`, `verdict`, or `diagnosis`
  to anything the live app returns.** `tests/test_app.py` enforces this by
  scanning the actual API response — it will fail your PR's tests if broken,
  which is the point. See `IMPLEMENTATION_NOTES.md`'s "The one rule
  everything else follows" for why.
- **Don't commit anything under `data/`, `artifacts/`, `outputs/`, or
  `.venv/`.** They're gitignored already — if `git status` shows one of
  these as untracked-but-wants-adding, that's a sign something's misconfigured,
  not a reason to force-add it.
- **Don't quote a validation number without its caveat.** If you touch
  anything in `training/splits.py` or report a metric from it, keep the
  `VAL_LEAKAGE_CAVEAT` / `HOLDOUT_CAVEAT` text attached — see `PHASE2.md`.
- **The reserved holdout set is Phase 4's to spend, once.** Don't add a code
  path that evaluates against it casually — see `training/splits.py` and
  `PHASE4.md`.
