"""Splitting the reserved held-out set into calibration and test halves.

training/splits.py reserves ``holdout`` and is explicit that it is "Phase
4's to spend, once" (see its module docstring, and PHASE2.md's "The held-out
set was not touched in Phase 2"). This module is that one spend: conformal
prediction needs two genuinely unseen-during-training-or-model-selection
partitions that are disjoint FROM EACH OTHER -- calibration data to fit the
per-class quantiles (scripts/calibrate_conformal.py), and test data to check
whether the resulting prediction sets actually achieve their claimed
coverage (scripts/evaluate_conformal.py). Both are drawn once, from
``holdout``, via the same stratified split training/splits.py already uses
for the (leaky, and separately labelled) fit/val partition.

This carries the identical caveat that split carries: not group-disjoint
from itself the way ``holdout`` is disjoint from ``fit``/``val`` -- there is
no further grouping available within holdout's own provenance groups, only
per-class stratification. What actually matters -- that neither half was
seen during training or checkpoint selection -- still holds, because both
come from the one partition that was never touched until now.
"""

from __future__ import annotations

from training.splits import stratified_split

HOLDOUT_SPLIT_CAVEAT = (
    "Calibration and test patches are a stratified random split of the "
    "reserved holdout set, not a group-disjoint one -- there is no further "
    "grouping available within holdout's own provenance groups. Both remain "
    "disjoint from fit and val (see training/splits.py), which is the "
    "guarantee that actually matters for these to be unseen by the model."
)


def split_holdout_for_conformal(
    source,
    holdout_ids: list[str],
    calibration_fraction: float,
    seed: int,
) -> tuple[list[str], list[str]]:
    """Return ``(calibration_ids, test_ids)``, both drawn from ``holdout_ids``.

    Reuses :func:`training.splits.stratified_split` so calibration keeps the
    same per-class stratification guarantee (and the same "at least one
    patch of a scarce class on each side" rule) as the fit/val split does.
    """
    test_ids, calibration_ids = stratified_split(
        source, holdout_ids, val_fraction=calibration_fraction, seed=seed
    )
    return sorted(calibration_ids), sorted(test_ids)
