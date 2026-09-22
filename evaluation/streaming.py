"""Bounded-memory building blocks for running Phase 4 at full holdout scale.

The Phase 4 scripts originally held every tissue pixel of every tile in
memory: float64 scores for all five classes (about 8 MB per tile) in
scripts/evaluate_conformal.py, and Python lists of every calibration pixel,
capped only afterwards, in scripts/calibrate_conformal.py. That is fine at the
52-tile smoke scale and impossible on the roughly 3,700 tiles of a full
holdout half on a 7.8 GB machine (about 30 GB). Two pieces replace it:

* :class:`PixelCounts` -- the four integers behind Eq. 5-7's pixel-level
  metrics. Counts add, so a metric over millions of pixels is a sum over
  tiles and no tile's pixels outlive the tile.
  :func:`evaluation.conformal.evaluate_prediction_mask` is the same
  computation on one concatenated array, and tests/test_streaming.py ties the
  two together.
* :class:`ScoreReservoir` -- a uniform random sample, without replacement, of
  at most ``capacity`` items from a stream. It draws from the distribution
  calibrate_conformal.py used to get by collecting everything and then calling
  ``rng.choice(..., replace=False)``; only the order the random numbers are
  drawn in differs, so a given seed does not reproduce an earlier run's exact
  sample.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from evaluation.conformal import ConformalMetrics


@dataclass(frozen=True)
class PixelCounts:
    """Running totals behind miscoverage, ambiguity and singleton accuracy."""

    n: int = 0
    missed: int = 0
    ambiguous: int = 0
    singleton_correct: int = 0

    @classmethod
    def from_mask(cls, mask: np.ndarray, true_classes: np.ndarray) -> "PixelCounts":
        """Counts for one (N, C) prediction-membership mask (see
        :func:`evaluation.conformal.prediction_mask`) and its N true classes."""
        mask = np.asarray(mask, dtype=bool)
        classes = np.asarray(true_classes, dtype=np.int64)
        n = mask.shape[0]
        if classes.shape[0] != n:
            raise ValueError("mask and true_classes must have the same length")

        ambiguous = mask.sum(axis=1) != 1
        contains_true = mask[np.arange(n), classes]
        return cls(
            n=n,
            missed=int((~contains_true).sum()),
            ambiguous=int(ambiguous.sum()),
            singleton_correct=int((~ambiguous & contains_true).sum()),
        )

    def __add__(self, other: "PixelCounts") -> "PixelCounts":
        return PixelCounts(
            n=self.n + other.n,
            missed=self.missed + other.missed,
            ambiguous=self.ambiguous + other.ambiguous,
            singleton_correct=self.singleton_correct + other.singleton_correct,
        )

    def metrics(self) -> ConformalMetrics:
        if self.n == 0:
            raise ValueError("Cannot evaluate metrics over zero predictions.")
        n_singleton = self.n - self.ambiguous
        return ConformalMetrics(
            miscoverage_rate=self.missed / self.n,
            ambiguity_rate=self.ambiguous / self.n,
            accuracy=(self.singleton_correct / n_singleton) if n_singleton else 0.0,
            n=self.n,
        )


class ScoreReservoir:
    """Uniform sample, without replacement, of at most ``capacity`` stream items.

    Every item gets an independent uniform random key and the ``capacity``
    smallest keys are kept. Keys are exchangeable, so the survivors are a
    uniformly random subset of everything seen, however the stream was
    batched. Each item carries an integer ``owner`` (here: the index of the
    tile it came from) so a per-tile attribute can be re-attached afterwards
    without storing it once per pixel.

    ``capacity=None`` keeps everything, for the ``--max-per-class 0`` case.
    """

    def __init__(self, capacity: int | None, seed: int) -> None:
        if capacity is not None and capacity < 1:
            raise ValueError(f"capacity must be at least 1 or None, got {capacity}")
        self.capacity = capacity
        self.seen = 0
        self._rng = np.random.default_rng(seed)
        self._keys = np.empty(0, dtype=np.float64)
        self._values = np.empty(0, dtype=np.float32)
        self._owners = np.empty(0, dtype=np.int32)

    def add(self, values: np.ndarray, owner: int) -> None:
        values = np.asarray(values, dtype=np.float32).reshape(-1)
        if values.size == 0:
            return
        self.seen += int(values.size)

        if self.capacity is None:
            keys = np.empty(0, dtype=np.float64)
        else:
            keys = self._rng.random(values.size)
            if values.size > self.capacity:
                # Only this batch's `capacity` smallest keys can survive the merge.
                keep = np.argpartition(keys, self.capacity - 1)[: self.capacity]
                keys, values = keys[keep], values[keep]

        self._values = np.concatenate([self._values, values])
        self._owners = np.concatenate(
            [self._owners, np.full(values.size, owner, dtype=np.int32)]
        )
        if self.capacity is None:
            return
        self._keys = np.concatenate([self._keys, keys])
        if self._keys.size > self.capacity:
            keep = np.argpartition(self._keys, self.capacity - 1)[: self.capacity]
            self._keys = self._keys[keep]
            self._values = self._values[keep]
            self._owners = self._owners[keep]

    def result(self) -> tuple[np.ndarray, np.ndarray]:
        """(values, owners), in no particular order."""
        return self._values, self._owners
