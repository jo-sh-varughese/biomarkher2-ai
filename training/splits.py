"""Train / validation / held-out splitting, and an honest account of it.

READ THIS BEFORE TRUSTING ANY VALIDATION NUMBER FROM PHASE 2.
==============================================================

The project brief requires that patches from the same slide never straddle a
train/validation boundary, because patch-level splitting in pathology inflates
validation metrics: adjacent patches from one slide are near-duplicates, so a
model that memorises a slide scores well on "unseen" patches from it.

That requirement **cannot be satisfied on HER2_IHC_40X**, and the reason is a
property of the dataset, not a shortcut taken here. Two measurements:

1. There are no slide identifiers. Filenames are
   ``her2-<score>-score_<train|test>_<n>.png`` where ``<n>`` is a sparse
   global counter (e.g. the 3634 patches of ``her2-0-score_train`` carry
   indices spanning 1..8443). Nothing in the dataset says which slide a patch
   came from. The coarsest available grouping is
   (slide score x origin directory) = 8 groups.

2. Those 8 groups are almost perfectly confounded with the label. Measured
   over all 10,997 patches:

       provenance             0     1+    2+    3+
       her2-0-score_train  3131    503     0     0
       her2-0-score_test    658     33     0     0
       her2-1+-score_train    0   1837   484    13
       her2-1+-score_test     0    316    13    11
       her2-2+-score_train    0      0   523     2
       her2-2+-score_test     0      0   111    10
       her2-3+-score_train    0      0     0  2600
       her2-3+-score_test     0      0     0   752

   Holding out any group removes an entire intensity class from training.
   Hold out the 3+ groups and the model never sees a strong-staining pixel.
   A group-wise split is therefore not merely coarse -- it is unusable.

3. **The directory division is not the dataset's own split.** ``data/raw``
   has ``train/`` and ``test/`` directories, and the obvious move is to hold
   out ``test/``. That was the first design here, and measuring it killed it.
   Filenames carry an origin token (``..._train_`` / ``..._test_``) recording
   a train/test assignment, and the directories cross it in both directions:

       directory   named _train_   named _test_
       train/            7,345          1,452
       test/             1,748            452

   78% of the files sitting in ``test/`` are named ``_train_``, and 17% of the
   files in ``train/`` are named ``_test_``. Both directories carry
   essentially the same mixture. A slide-aware partition does not look like
   that; a random re-shuffle does. So the directory layout is a re-packaging,
   and holding out ``test/`` would hold out a random sample of the same
   slides -- leakage, wearing the costume of a held-out set.

What this module does instead
-----------------------------

* **Held-out set = every patch whose *filename* origin token is ``test``**,
  regardless of which directory it sits in. This is chosen over the directory
  layout for one reason: when two divisions disagree, the one more likely to
  be the authors' original is the one baked into the filenames. Someone
  re-packaging a dataset into new folders does not rewrite every filename;
  the reverse -- authors encoding a split in filenames, a packager reshuffling
  the folders -- is exactly the pattern measured above.

  This is an **inference from file naming, not a verified slide partition**.
  It is the best available approximation and is labelled as such. It does
  guarantee one real thing: fit and holdout share no provenance group, which
  :func:`assert_no_group_overlap` asserts on every call.

* **Validation set = a stratified random draw from the remaining patches.**
  With no sub-grouping available there is no leakage-free way to do this. So
  this split is explicitly labelled ``leakage_free=False``. It exists to
  choose a stopping epoch and to draw learning curves -- nothing more. Any
  report that quotes it as a generalization estimate is wrong, and
  :meth:`SplitResult.caveat` carries that sentence into the artifacts so it
  travels with the numbers.

Neither caveat goes away by trying harder. A genuinely defensible held-out
evaluation needs data with slide identity, which means the Kottayam slides.
When those arrive, :func:`grouped_split` is already here and correct; point it
at a source whose ``group_key`` returns a slide ID and the brief's requirement
is met properly, for real.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

VAL_LEAKAGE_CAVEAT = (
    "Validation patches are drawn at random from the same directory as the "
    "training patches. HER2_IHC_40X carries no slide identifiers, so patches "
    "from one slide may appear on both sides. Validation metrics are "
    "therefore optimistic and are used only for epoch selection and curves. "
    "The held-out set is defined by the filename origin token instead."
)

HOLDOUT_CAVEAT = (
    "The held-out set is defined by the origin token in each patch's filename, "
    "which is inferred to be the dataset authors' own train/test assignment. "
    "It is NOT a verified slide-level partition -- HER2_IHC_40X carries no "
    "slide identifiers. The train/ and test/ directories were measured to "
    "cross this token in both directions and are therefore a re-packaging, not "
    "a split. Held-out metrics are the best estimate available from this "
    "dataset and are still not a substitute for evaluation on slides with "
    "known identity."
)


@dataclass
class SplitResult:
    """The patch ids on each side, plus how they were obtained."""

    fit: list[str]
    val: list[str]
    holdout: list[str]
    method: str
    leakage_free: bool
    group_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    class_counts: dict[str, dict[int, int]] = field(default_factory=dict)

    holdout_caveat: str | None = HOLDOUT_CAVEAT

    @property
    def caveat(self) -> str | None:
        return None if self.leakage_free else VAL_LEAKAGE_CAVEAT

    def summary(self) -> dict:
        return {
            "method": self.method,
            "leakage_free": self.leakage_free,
            "caveat": self.caveat,
            "holdout_caveat": self.holdout_caveat,
            "sizes": {
                "fit": len(self.fit),
                "val": len(self.val),
                "holdout": len(self.holdout),
            },
            "class_counts": {
                side: {str(k): v for k, v in counts.items()}
                for side, counts in self.class_counts.items()
            },
            "group_counts": self.group_counts,
        }

    def write(self, path: str | Path) -> None:
        """Persist the split so a rerun can be checked against it."""
        payload = self.summary() | {
            "patch_ids": {"fit": self.fit, "val": self.val, "holdout": self.holdout}
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)


def assert_no_group_overlap(source, left: list[str], right: list[str]) -> None:
    """Raise if any group key appears on both sides.

    The check the brief asks for, kept as a callable so it can be applied to
    whatever grouping a future data source does provide.
    """
    left_groups = {source.group_key(pid) for pid in left}
    right_groups = {source.group_key(pid) for pid in right}
    shared = left_groups & right_groups
    if shared:
        raise ValueError(
            f"Group leakage: {len(shared)} group(s) appear on both sides of the "
            f"split, e.g. {sorted(shared)[:5]}"
        )


def grouped_split(
    source,
    patch_ids: list[str],
    val_fraction: float,
    seed: int,
    require_all_classes: bool = True,
) -> tuple[list[str], list[str]]:
    """Split whole groups, never individual patches.

    Correct, and unusable on HER2_IHC_40X for the reason in the module
    docstring -- it raises rather than returning a class-incomplete split.
    Kept for the day a source provides real slide IDs.
    """
    by_group: dict[str, list[str]] = defaultdict(list)
    for pid in patch_ids:
        by_group[source.group_key(pid)].append(pid)

    groups = sorted(by_group)
    if len(groups) < 2:
        raise ValueError(
            f"Cannot build a grouped split from {len(groups)} group(s). "
            "The source provides no usable grouping."
        )

    rng = np.random.default_rng(seed)
    order = rng.permutation(len(groups))
    target = val_fraction * len(patch_ids)

    val_groups: set[str] = set()
    taken = 0
    for idx in order:
        if taken >= target:
            break
        group = groups[idx]
        val_groups.add(group)
        taken += len(by_group[group])

    fit = [p for g in groups if g not in val_groups for p in by_group[g]]
    val = [p for g in groups if g in val_groups for p in by_group[g]]

    if require_all_classes:
        _require_all_classes(source, {"fit": fit, "val": val}, context="grouped split")
    assert_no_group_overlap(source, fit, val)
    return sorted(fit), sorted(val)


def stratified_split(
    source,
    patch_ids: list[str],
    val_fraction: float,
    seed: int,
    stratify: bool = True,
) -> tuple[list[str], list[str]]:
    """Random split, optionally preserving the class distribution.

    NOT leakage-free. Only used where no grouping exists -- see the module
    docstring.
    """
    if not 0.0 < val_fraction < 1.0:
        raise ValueError(f"val_fraction must be in (0, 1), got {val_fraction}")

    rng = np.random.default_rng(seed)
    strata: dict[object, list[str]] = defaultdict(list)
    for pid in sorted(patch_ids):
        key = source.label(pid) if stratify else None
        strata[key].append(pid)

    fit: list[str] = []
    val: list[str] = []
    for key in sorted(strata, key=lambda k: (k is None, k)):
        members = strata[key]
        shuffled = [members[i] for i in rng.permutation(len(members))]
        # At least one patch per stratum on each side, so a scarce class such
        # as 2+ cannot vanish from validation through rounding.
        n_val = int(round(val_fraction * len(shuffled)))
        n_val = max(1, min(n_val, len(shuffled) - 1)) if len(shuffled) > 1 else 0
        val.extend(shuffled[:n_val])
        fit.extend(shuffled[n_val:])
    return sorted(fit), sorted(val)


def stratified_subsample(
    source, patch_ids: list[str], cap: int | None, seed: int
) -> list[str]:
    """Take at most ``cap`` patches while keeping every class represented.

    Necessary because patch ids sort by class folder: ``ids[:cap]`` on a
    sorted list yields nothing but class_0 patches. A smoke run built that way
    trains on one class, reports a plausible loss curve, and is worthless. Any
    cap applied anywhere in Phase 2 goes through here.
    """
    if cap is None or cap >= len(patch_ids):
        return sorted(patch_ids)

    rng = np.random.default_rng(seed)
    strata: dict[object, list[str]] = defaultdict(list)
    for pid in sorted(patch_ids):
        strata[source.label(pid)].append(pid)

    shuffled = {
        key: [members[i] for i in rng.permutation(len(members))]
        for key, members in strata.items()
    }
    # Round-robin rather than proportional: with a small cap, proportional
    # allocation rounds a scarce class down to zero, which is the failure this
    # function exists to prevent.
    chosen: list[str] = []
    depth = 0
    while len(chosen) < cap:
        added = False
        for key in sorted(shuffled, key=lambda k: (k is None, k)):
            if depth < len(shuffled[key]) and len(chosen) < cap:
                chosen.append(shuffled[key][depth])
                added = True
        if not added:
            break
        depth += 1
    return sorted(chosen)


def holdout_key(record, holdout_by: str) -> str:
    """The value that decides which side of the held-out boundary a patch is on.

    ``filename_origin`` reads the ``_train_`` / ``_test_`` token the dataset
    authors baked into each filename. ``directory`` reads the folder the file
    happens to sit in -- available, measured to be a re-shuffle, and offered
    only so the difference can be reproduced rather than taken on trust.
    """
    if holdout_by == "filename_origin":
        # provenance is "her2-<slide score>-score_<origin>"; the origin token
        # is the part after the final underscore.
        provenance = getattr(record, "provenance", "") or ""
        if "_" not in provenance:
            raise ValueError(
                f"Patch {record.patch_id!r} has provenance {provenance!r}, which "
                "carries no origin token. Use holdout_by='directory' for a "
                "source whose filenames do not follow the HER2_IHC_40X "
                "convention."
            )
        return provenance.rsplit("_", 1)[-1]
    if holdout_by == "directory":
        return record.split
    raise ValueError(
        f"Unknown holdout_by {holdout_by!r}; expected 'filename_origin' or "
        "'directory'."
    )


def build_splits(source, config, records=None) -> SplitResult:
    """Produce the fit / val / holdout split described in the module docstring.

    ``source`` must expose ``records()`` yielding objects with ``patch_id``,
    ``split`` and ``provenance``, as
    :class:`preprocessing.sources.DirectoryPatchSource` does.
    """
    records = list(records if records is not None else source.records())
    by_key: dict[str, list[str]] = defaultdict(list)
    for record in records:
        by_key[holdout_key(record, config.holdout_by)].append(record.patch_id)

    if config.holdout_value not in by_key:
        raise ValueError(
            f"No patches have {config.holdout_by} == {config.holdout_value!r}. "
            f"Available: {sorted(by_key)}"
        )
    if len(by_key) < 2:
        raise ValueError(
            f"Every patch has {config.holdout_by} == {config.holdout_value!r}; "
            "there is nothing left to train on."
        )

    holdout = sorted(by_key[config.holdout_value])
    remainder = [p for k, ids in by_key.items() if k != config.holdout_value
                 for p in ids]
    fit, val = stratified_split(
        source,
        remainder,
        val_fraction=config.val_fraction,
        seed=config.seed,
        stratify=config.stratify,
    )

    sides = {"fit": fit, "val": val, "holdout": holdout}
    if config.require_all_classes:
        _require_all_classes(source, sides, context="fit/val/holdout split")

    # Fit/val and holdout are group-disjoint even though fit and val are not,
    # because provenance encodes the origin token the holdout is defined by.
    # Assert the part that is actually true rather than skipping the check.
    assert_no_group_overlap(source, fit + val, holdout)

    return SplitResult(
        fit=fit,
        val=val,
        holdout=holdout,
        method=(
            f"holdout = patches with {config.holdout_by} == "
            f"'{config.holdout_value}'; fit/val = stratified random draw from "
            f"the rest (val_fraction={config.val_fraction}, seed={config.seed})"
        ),
        leakage_free=False,
        group_counts={
            side: dict(Counter(source.group_key(p) for p in ids))
            for side, ids in sides.items()
        },
        class_counts={
            side: dict(Counter(source.label(p) for p in ids))
            for side, ids in sides.items()
        },
    )


def _require_all_classes(source, sides: dict[str, list[str]], context: str) -> None:
    all_classes = {source.label(p) for ids in sides.values() for p in ids}
    all_classes.discard(None)
    for side, ids in sides.items():
        present = {source.label(p) for p in ids}
        missing = all_classes - present
        if missing:
            raise ValueError(
                f"{context}: side {side!r} is missing class(es) {sorted(missing)}. "
                "Metrics from a class-incomplete split are meaningless; refusing "
                "to continue."
            )
