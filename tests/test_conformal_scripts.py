"""The full-scale changes to scripts/calibrate_conformal.py and scripts/evaluate_conformal.py.

The streaming evaluation must give exactly the numbers the earlier
concatenate-every-tile version gave; the reference below is that version's
logic, written out with the library functions it used.
"""

import numpy as np
import pytest
import torch

from evaluation.conformal import (
    ConformalCalibrator,
    aggregate_patch_status_from_mask,
    evaluate_patch_statuses,
    evaluate_prediction_mask,
    hinge_scores,
    prediction_mask,
)
from models.unet_seg import normalize_batch
from preprocessing.config import PreprocessingConfig
from preprocessing.pipeline import PreprocessingPipeline
from scripts.calibrate_conformal import collect_calibration_scores
from scripts.evaluate_conformal import iter_test_tiles, stream_evaluation
from tests.synthetic import graded_patch
from training.pseudo_labels import PseudoLabelCache, build_cache

ALPHAS = [0.1, 0.3]


def _softmax(logits):
    e = np.exp(logits - logits.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


def _synthetic_tiles(rng, n_tiles=6):
    tiles = []
    for _ in range(n_tiles):
        n = int(rng.integers(200, 600))
        tiles.append(
            {
                "scores": hinge_scores(_softmax(rng.normal(size=(n, 5)) * 2.0)),
                "true": rng.integers(1, 5, size=n),
                "descriptor": rng.normal(size=6),
            }
        )
    return tiles


def _calibrator(rng):
    scores = {c: rng.random(400) for c in range(1, 5)}
    descriptors = {c: rng.normal(size=(400, 6)) for c in range(1, 5)}
    return ConformalCalibrator.fit(scores, descriptors)


def _reference(calibrator, bandwidth, tiles, alpha, weighted):
    masks, truths, statuses, patch_true = [], [], [], []
    for tile in tiles:
        quantiles = {
            c: calib.quantile(
                alpha,
                test_descriptor=tile["descriptor"] if weighted else None,
                bandwidth=bandwidth if weighted else None,
            )
            for c, calib in calibrator.by_class.items()
        }
        mask = prediction_mask(tile["scores"], quantiles)
        masks.append(mask)
        truths.append(tile["true"])
        statuses.append(aggregate_patch_status_from_mask(mask))
        values, counts = np.unique(tile["true"], return_counts=True)
        patch_true.append(int(values[np.argmax(counts)]))
    return (
        evaluate_prediction_mask(np.concatenate(masks), np.concatenate(truths)),
        evaluate_patch_statuses(statuses, patch_true),
    )


def test_streaming_evaluation_matches_the_concatenate_everything_version_exactly():
    rng = np.random.default_rng(0)
    calibrator, tiles = _calibrator(rng), _synthetic_tiles(rng)

    results, n_tiles = stream_evaluation(calibrator, 1.0, iter(tiles), ALPHAS)

    assert n_tiles == len(tiles)
    assert set(results) == {(a, w) for a in ALPHAS for w in (False, True)}
    for (alpha, weighted), (pixel, patch) in results.items():
        expected_pixel, expected_patch = _reference(calibrator, 1.0, tiles, alpha, weighted)
        assert pixel == expected_pixel
        assert patch == expected_patch


def test_streaming_evaluation_with_no_tiles_is_an_error():
    with pytest.raises(ValueError):
        stream_evaluation(_calibrator(np.random.default_rng(1)), 1.0, iter([]), ALPHAS)


class TinyModel(torch.nn.Module):
    """Stands in for the U-Net: 4 channels in, 5 class logits out, same size."""

    def __init__(self):
        super().__init__()
        torch.manual_seed(0)
        self.head = torch.nn.Conv2d(4, 5, 1)

    def forward(self, pixels):
        return self.head(pixels)


def _cache_with_labelled_tiles(tmp_path):
    """Two cached 64x64 tiles with hand-set labels: one all class 2, one all class 3."""
    cache = PseudoLabelCache(tmp_path / "cache")
    rgb = graded_patch(size=64)
    ids = []
    for name, cls in (("a", 2), ("b", 3)):
        tile_id = cache.tile_id(f"test/class_{cls}/{name}.png", 0, 0)
        label = np.full((64, 64), cls, dtype=np.uint8)
        label[:8, :8] = 0  # a little background, so tissue != everything
        cache.write(tile_id, rgb, label)
        ids.append(tile_id)
    return cache, ids


def test_iter_test_tiles_yields_scores_labels_and_a_descriptor_per_tissue_tile(tmp_path):
    cache, ids = _cache_with_labelled_tiles(tmp_path)

    tiles = iter_test_tiles(TinyModel(), normalize_batch, 4, cache, ids, "cpu")
    first = next(tiles)

    assert first["scores"].shape == (64 * 64 - 64, 5)
    assert set(np.unique(first["true"])) == {2}
    assert first["descriptor"].shape == (6,)
    assert len(list(tiles)) == 1  # a generator: the second tile is still to come


def test_calibration_reservoirs_keep_each_pixel_with_its_own_tiles_descriptor(tmp_path):
    cache, ids = _cache_with_labelled_tiles(tmp_path)

    reservoirs, descriptors = collect_calibration_scores(
        TinyModel(), normalize_batch, 4, cache, ids, "cpu", max_per_class=None, seed=0
    )

    assert len(descriptors) == 2
    _, owners_class2 = reservoirs[2].result()
    _, owners_class3 = reservoirs[3].result()
    assert set(owners_class2.tolist()) == {0}  # tile "a" is all class 2
    assert set(owners_class3.tolist()) == {1}  # tile "b" is all class 3
    assert reservoirs[1].seen == 0 and reservoirs[4].seen == 0


def test_calibration_cap_bounds_what_is_kept_but_not_what_is_counted(tmp_path):
    cache, ids = _cache_with_labelled_tiles(tmp_path)

    reservoirs, _ = collect_calibration_scores(
        TinyModel(), normalize_batch, 4, cache, ids, "cpu", max_per_class=100, seed=0
    )

    scores, owners = reservoirs[2].result()
    assert len(scores) == len(owners) == 100
    assert reservoirs[2].seen == 64 * 64 - 64
