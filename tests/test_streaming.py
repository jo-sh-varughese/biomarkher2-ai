import numpy as np
import pytest

from evaluation.conformal import evaluate_prediction_mask
from evaluation.streaming import PixelCounts, ScoreReservoir


def _random_case(rng, n, classes=5):
    mask = rng.random((n, classes)) < 0.35
    true = rng.integers(0, classes, size=n)
    return mask, true


def test_pixel_counts_summed_over_chunks_equal_the_one_shot_metrics():
    rng = np.random.default_rng(0)
    mask, true = _random_case(rng, 6000)
    expected = evaluate_prediction_mask(mask, true)

    for chunk in (1, 7, 500, 6000):
        total = PixelCounts()
        for start in range(0, len(true), chunk):
            total = total + PixelCounts.from_mask(mask[start:start + chunk], true[start:start + chunk])
        assert total.metrics() == expected


def test_pixel_counts_accuracy_is_zero_when_every_prediction_is_ambiguous():
    mask = np.ones((4, 3), dtype=bool)

    metrics = PixelCounts.from_mask(mask, np.array([0, 1, 2, 0])).metrics()

    assert metrics.ambiguity_rate == 1.0
    assert metrics.accuracy == 0.0


def test_pixel_counts_reject_mismatched_lengths_and_empty_totals():
    with pytest.raises(ValueError):
        PixelCounts.from_mask(np.ones((3, 2), dtype=bool), np.array([0, 1]))
    with pytest.raises(ValueError):
        PixelCounts().metrics()


def test_reservoir_keeps_everything_when_under_capacity():
    reservoir = ScoreReservoir(capacity=100, seed=0)
    reservoir.add(np.array([0.1, 0.2, 0.3]), owner=0)
    reservoir.add(np.array([0.4, 0.5]), owner=1)

    values, owners = reservoir.result()

    assert sorted(values.tolist()) == pytest.approx([0.1, 0.2, 0.3, 0.4, 0.5])
    assert sorted(owners.tolist()) == [0, 0, 0, 1, 1]
    assert reservoir.seen == 5


def test_reservoir_never_exceeds_capacity_and_only_returns_items_it_was_given():
    reservoir = ScoreReservoir(capacity=10, seed=1)
    items = np.arange(500, dtype=np.float32)
    # one batch far larger than the capacity, then many small ones
    reservoir.add(items[:300], owner=0)
    for start in range(300, 500, 20):
        reservoir.add(items[start:start + 20], owner=start)

    values, owners = reservoir.result()

    assert len(values) == len(owners) == 10
    assert len(set(values.tolist())) == 10
    assert set(values.tolist()) <= set(items.tolist())
    assert reservoir.seen == 500


def test_reservoir_keeps_each_item_paired_with_its_owner():
    reservoir = ScoreReservoir(capacity=6, seed=2)
    reservoir.add(np.arange(0, 10, dtype=np.float32), owner=7)
    reservoir.add(np.arange(10, 20, dtype=np.float32), owner=9)

    values, owners = reservoir.result()

    for value, owner in zip(values, owners):
        assert owner == (7 if value < 10 else 9)


def test_reservoir_is_uniform_however_the_stream_is_batched():
    # 20 items arriving as batches of 7, 3 and 10, capacity 5: every item must
    # survive with probability 5/20, including items from the small batch.
    trials = 4000
    hits = np.zeros(20)
    items = np.arange(20, dtype=np.float32)
    for seed in range(trials):
        reservoir = ScoreReservoir(capacity=5, seed=seed)
        reservoir.add(items[:7], owner=0)
        reservoir.add(items[7:10], owner=1)
        reservoir.add(items[10:], owner=2)
        hits[reservoir.result()[0].astype(int)] += 1

    frequency = hits / trials
    assert np.all(np.abs(frequency - 0.25) < 0.04)


def test_reservoir_without_a_capacity_keeps_everything():
    reservoir = ScoreReservoir(capacity=None, seed=0)
    reservoir.add(np.arange(50, dtype=np.float32), owner=3)

    values, owners = reservoir.result()

    assert len(values) == 50 and set(owners.tolist()) == {3}


def test_reservoir_ignores_an_empty_batch_and_rejects_a_bad_capacity():
    reservoir = ScoreReservoir(capacity=3, seed=0)
    reservoir.add(np.array([]), owner=0)

    assert reservoir.seen == 0 and len(reservoir.result()[0]) == 0
    with pytest.raises(ValueError):
        ScoreReservoir(capacity=0, seed=0)
