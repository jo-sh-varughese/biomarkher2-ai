"""Tests for split correctness -- the anti-leakage requirement.

These are the tests that matter most in Phase 2. A leaking split does not
crash, does not warn, and makes every metric look better; the only thing that
catches it is a test that constructs a leak on purpose and demands a failure.
"""

from __future__ import annotations

import pytest

from training.config import SplitConfig
from training.splits import (
    HOLDOUT_CAVEAT,
    VAL_LEAKAGE_CAVEAT,
    assert_no_group_overlap,
    build_splits,
    grouped_split,
    stratified_split,
    stratified_subsample,
)


class FakeRecord:
    def __init__(self, patch_id, group, label, split):
        self.patch_id = patch_id
        self.provenance = group
        self.patch_class = label
        self.split = split


class FakeSource:
    """A source with real slide-level groups -- what HER2_IHC_40X lacks."""

    def __init__(self, records):
        self._records = {r.patch_id: r for r in records}

    def list_ids(self):
        return sorted(self._records)

    def records(self):
        return [self._records[i] for i in self.list_ids()]

    def group_key(self, patch_id):
        return self._records[patch_id].provenance

    def label(self, patch_id):
        return self._records[patch_id].patch_class


def slide_source(slides=6, per_slide=10, origins=("train",), directory=None):
    """Slides carrying every class, so a grouped split stays class-complete.

    ``origins`` are filename origin tokens; ``directory`` overrides the folder
    a patch sits in, so the two can be made to disagree the way they do in the
    real dataset.
    """
    records = []
    for origin in origins:
        for s in range(slides):
            for p in range(per_slide):
                records.append(
                    FakeRecord(
                        patch_id=f"{origin}/slide{s:02d}/patch{p:02d}",
                        # Ends in the origin token, as real provenance does,
                        # while still naming a distinct group per slide.
                        group=f"slide{s:02d}_{origin}",
                        label=1 + (p % 4),
                        split=directory or origin,
                    )
                )
    return FakeSource(records)


def test_grouped_split_puts_no_slide_on_both_sides():
    source = slide_source()
    fit, val = grouped_split(source, source.list_ids(), val_fraction=0.3, seed=1)

    fit_groups = {source.group_key(p) for p in fit}
    val_groups = {source.group_key(p) for p in val}
    assert fit_groups and val_groups
    assert not (fit_groups & val_groups)


def test_grouped_split_covers_every_patch_exactly_once():
    source = slide_source()
    fit, val = grouped_split(source, source.list_ids(), val_fraction=0.3, seed=1)
    assert sorted(fit + val) == source.list_ids()
    assert not set(fit) & set(val)


def test_assert_no_group_overlap_catches_a_deliberate_leak():
    """The check must fail on a split that leaks, or it is worth nothing."""
    source = slide_source()
    ids = source.list_ids()
    leaked_fit = ids[:40]
    # Overlap by one slide's worth of patches, from the same group.
    leaked_val = [p for p in ids if source.group_key(p) == source.group_key(ids[0])]

    with pytest.raises(ValueError, match="Group leakage"):
        assert_no_group_overlap(source, leaked_fit, leaked_val)


def test_grouped_split_refuses_when_a_class_would_disappear():
    """The HER2_IHC_40X failure mode, reproduced deliberately.

    Each group holds exactly one class, so holding out any group removes that
    class from training. The split must raise rather than return.
    """
    records = [
        FakeRecord(f"train/g{c}/p{i:02d}", f"group{c}", c, "train")
        for c in (1, 2, 3, 4)
        for i in range(10)
    ]
    source = FakeSource(records)
    with pytest.raises(ValueError, match="missing class"):
        grouped_split(source, source.list_ids(), val_fraction=0.25, seed=0)


def test_stratified_split_preserves_class_proportions():
    source = slide_source()
    fit, val = stratified_split(source, source.list_ids(), val_fraction=0.2, seed=3)

    for cls in (1, 2, 3, 4):
        in_val = sum(source.label(p) == cls for p in val)
        in_fit = sum(source.label(p) == cls for p in fit)
        assert in_val > 0, f"class {cls} vanished from validation"
        assert abs(in_val / (in_val + in_fit) - 0.2) < 0.06


def test_stratified_split_keeps_a_scarce_class_on_both_sides():
    """One class with two patches must not round away to zero."""
    records = [FakeRecord(f"train/g/p{i:02d}", "g", 1, "train") for i in range(50)]
    records += [FakeRecord(f"train/g/rare{i}", "g", 3, "train") for i in range(2)]
    source = FakeSource(records)

    fit, val = stratified_split(source, source.list_ids(), val_fraction=0.1, seed=0)
    assert any(source.label(p) == 3 for p in val)
    assert any(source.label(p) == 3 for p in fit)


def test_build_splits_keeps_holdout_disjoint_from_everything():
    source = slide_source(origins=("train", "test"))
    result = build_splits(source, SplitConfig())

    assert set(result.holdout) & set(result.fit) == set()
    assert set(result.holdout) & set(result.val) == set()
    assert all(p.startswith("test/") for p in result.holdout)
    assert all(not p.startswith("test/") for p in result.fit + result.val)


def test_build_splits_shares_no_provenance_group_with_the_holdout():
    """The one leakage guarantee this dataset does support."""
    source = slide_source(origins=("train", "test"))
    result = build_splits(source, SplitConfig())
    assert_no_group_overlap(source, result.fit + result.val, result.holdout)


def test_holdout_follows_the_filename_token_not_the_directory():
    """The finding that forced this design, pinned as a test.

    Every patch here sits in a directory called "test" while its filename
    origin token says "train". Splitting on the directory would hold out
    everything; splitting on the filename must hold out nothing -- and so
    must raise, because there would be no held-out set at all.
    """
    source = slide_source(origins=("train",), directory="test")

    with pytest.raises(ValueError, match="No patches have"):
        build_splits(source, SplitConfig(holdout_by="filename_origin"))

    with pytest.raises(ValueError, match="nothing left to train on"):
        build_splits(source, SplitConfig(holdout_by="directory"))


def test_directory_mode_still_works_for_sources_that_warrant_it():
    source = slide_source(origins=("train", "test"))
    result = build_splits(source, SplitConfig(holdout_by="directory"))
    assert all(p.startswith("test/") for p in result.holdout)


def test_unknown_holdout_key_is_rejected():
    source = slide_source(origins=("train", "test"))
    with pytest.raises(ValueError, match="Unknown holdout_by"):
        build_splits(source, SplitConfig(holdout_by="slide_id"))


def test_build_splits_is_reproducible_for_a_fixed_seed():
    source = slide_source(origins=("train", "test"))
    first = build_splits(source, SplitConfig())
    second = build_splits(source, SplitConfig())
    assert first.fit == second.fit
    assert first.val == second.val


def test_build_splits_carries_both_caveats():
    """The caveats must travel with the numbers, not live only in a docstring."""
    source = slide_source(origins=("train", "test"))
    result = build_splits(source, SplitConfig())

    assert result.leakage_free is False
    assert result.caveat == VAL_LEAKAGE_CAVEAT
    assert result.summary()["caveat"] == VAL_LEAKAGE_CAVEAT
    assert result.summary()["holdout_caveat"] == HOLDOUT_CAVEAT
    assert "not a verified slide-level partition" in HOLDOUT_CAVEAT.lower()


def test_build_splits_written_artifact_contains_the_caveat(tmp_path):
    import json

    source = slide_source(origins=("train", "test"))
    result = build_splits(source, SplitConfig())
    path = tmp_path / "split.json"
    result.write(path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["caveat"] == VAL_LEAKAGE_CAVEAT
    assert payload["leakage_free"] is False
    assert len(payload["patch_ids"]["fit"]) == len(result.fit)


def test_subsample_keeps_every_class_where_a_slice_would_not():
    """Patch ids sort by class folder, so ids[:cap] is one class only."""
    records = [
        FakeRecord(f"train/class_{c}/p{i:03d}", "g", c, "train")
        for c in (1, 2, 3, 4)
        for i in range(100)
    ]
    source = FakeSource(records)
    ids = source.list_ids()

    assert len({source.label(p) for p in ids[:40]}) == 1  # the bug, demonstrated

    kept = stratified_subsample(source, ids, cap=40, seed=0)
    assert len(kept) == 40
    assert {source.label(p) for p in kept} == {1, 2, 3, 4}


def test_subsample_does_not_round_a_scarce_class_away():
    records = [FakeRecord(f"train/class_1/p{i:03d}", "g", 1, "train") for i in range(500)]
    records += [FakeRecord("train/class_3/rare", "g", 3, "train")]
    source = FakeSource(records)

    kept = stratified_subsample(source, source.list_ids(), cap=10, seed=0)
    assert 3 in {source.label(p) for p in kept}


def test_subsample_is_a_no_op_when_the_cap_exceeds_the_data():
    source = slide_source()
    ids = source.list_ids()
    assert stratified_subsample(source, ids, cap=None, seed=0) == ids
    assert stratified_subsample(source, ids, cap=10_000, seed=0) == ids


def test_subsample_is_reproducible():
    source = slide_source()
    ids = source.list_ids()
    assert stratified_subsample(source, ids, 20, seed=5) == stratified_subsample(
        source, ids, 20, seed=5
    )


def test_build_splits_raises_when_no_patch_is_held_out():
    source = slide_source(origins=("train",))
    with pytest.raises(ValueError, match="No patches have"):
        build_splits(source, SplitConfig())
