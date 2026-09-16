"""Tests for analysis of images larger than one model tile.

app/analysis.py's Analyzer.predict() tiles an image of any size and stitches
predictions back -- built ahead of real whole-slide images so Phase 3/6
wouldn't need new stitching logic, just a bigger input. Before this file
existed, that had never been exercised above single-patch scale. Two things
are worth checking and they are not the same kind of bug:

* Coverage -- does the stitched output actually cover every pixel, with the
  right shape and dtype (test_analysis_large_image_covers_all_tiles).
* Coordinate correctness -- is a given tile's prediction the same regardless
  of where it sits in the larger image (test_analysis_large_image_tile_coordinates_are_correct).
  A shape/dtype check alone would still pass even if tiles were placed with a
  transposed row/col or an off-by-one, because the output would still be the
  right size and full of valid class values -- just wrong ones. See
  scripts/build_mock_slide.py's --analyze flag for the same check run
  against a real trained checkpoint and a real mock slide, not just this
  synthetic case.
"""

from __future__ import annotations

import numpy as np
import torch

from app.analysis import Analyzer
from models import select_architecture
from preprocessing.baseline import NUM_CLASSES
from tests.synthetic import positioned_grid
from training.config import TrainingConfig


def _make_analyzer(tmp_path):
    config = TrainingConfig()
    config.model.pretrained = False
    config.model.image_size = 64
    config.to_yaml(tmp_path / "training.yaml")

    build_model, _ = select_architecture(config.model.architecture)
    model = build_model(config.model, verbose=False)

    torch.save(
        {
            "model_state": model.state_dict(),
            "epoch": 1,
            "caveat": "test",
        },
        tmp_path / "best.pt",
    )

    return Analyzer(
        tmp_path,
        tmp_path / "training.yaml",
        "configs/preprocessing.yaml",
    )


def test_analysis_large_image_covers_all_tiles(tmp_path):
    """A 2x2 image must receive predictions across its complete area."""
    analyzer = _make_analyzer(tmp_path)

    tile_size = analyzer.tile_size

    rgb = np.random.default_rng(42).integers(
        60,
        220,
        (tile_size * 2, tile_size * 2, 3),
        dtype=np.uint8,
    )

    prediction = analyzer.predict(rgb)

    assert prediction.shape == rgb.shape[:2]
    assert prediction.dtype == np.uint8
    assert prediction.min() >= 0
    assert prediction.max() < NUM_CLASSES

    # Every corner belongs to a real predicted tile.
    assert prediction[0, 0] >= 0
    assert prediction[0, -1] >= 0
    assert prediction[-1, 0] >= 0
    assert prediction[-1, -1] >= 0


def test_analysis_large_image_tile_coordinates_are_correct(tmp_path):
    """A tile's prediction must not depend on where in a larger image it sits.

    Builds a 2x2 mosaic where every tile carries content unique to its own
    grid position (tests/synthetic.py's positioned_grid), predicts the whole
    mosaic in one call, then predicts each tile again on its own and checks
    the two agree exactly. A coordinate mixup in the tiling loop (rows and
    columns swapped, an off-by-one in the tile offsets) would make a tile
    disagree with itself here even though the mosaic's overall shape still
    looks correct.
    """
    analyzer = _make_analyzer(tmp_path)
    tile_size = analyzer.tile_size

    mosaic = positioned_grid(tile_size=tile_size, rows=2, cols=2)
    stitched = analyzer.predict(mosaic)
    assert stitched.shape == mosaic.shape[:2]

    for row in range(2):
        for col in range(2):
            tile = mosaic[
                row * tile_size : (row + 1) * tile_size,
                col * tile_size : (col + 1) * tile_size,
            ]
            standalone = analyzer.predict(tile)
            from_mosaic = stitched[
                row * tile_size : (row + 1) * tile_size,
                col * tile_size : (col + 1) * tile_size,
            ]
            assert np.array_equal(from_mosaic, standalone), (
                f"tile (row={row}, col={col}) predicts differently "
                "in-place vs. standalone"
            )
