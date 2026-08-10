"""Tests for tiling geometry and coordinate bookkeeping.

Coordinate errors here are silent -- a heatmap built on an off-by-one tile
grid still looks like a plausible heatmap. The positional tests decode each
tile's own pixels back into the grid position it claims to come from, so a
mismatch is caught rather than rendered.
"""

from __future__ import annotations

import numpy as np
import pytest

from preprocessing.config import TilingConfig
from preprocessing.tiling import Tile, downsample, extract_tiles, tile_positions
from tests.synthetic import positioned_grid, synthetic_patch


def test_tile_positions_cover_exact_grid():
    positions = tile_positions(64, 64, patch_size=16, overlap=0, drop_partial=True)
    assert len(positions) == 16
    assert {(y, x) for _, _, y, x in positions} == {
        (r * 16, c * 16) for r in range(4) for c in range(4)
    }


def test_tile_positions_respect_overlap():
    positions = tile_positions(32, 32, patch_size=16, overlap=8, drop_partial=True)
    xs = sorted({x for _, _, _, x in positions})
    assert xs == [0, 8, 16]


def test_partial_tiles_dropped_by_default():
    positions = tile_positions(20, 20, patch_size=16, overlap=0, drop_partial=True)
    assert len(positions) == 1
    assert positions[0][2:] == (0, 0)


def test_partial_tiles_snap_to_edge_when_not_dropped():
    """Snapping keeps tiles full-size instead of zero-padding fake background."""
    positions = tile_positions(20, 20, patch_size=16, overlap=0, drop_partial=False)
    coords = {(y, x) for _, _, y, x in positions}
    assert (4, 4) in coords
    for _, _, y, x in positions:
        assert y + 16 <= 20 and x + 16 <= 20


def test_overlap_must_be_smaller_than_patch():
    with pytest.raises(ValueError, match="overlap"):
        tile_positions(64, 64, patch_size=16, overlap=16, drop_partial=True)


def test_negative_overlap_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        tile_positions(64, 64, patch_size=16, overlap=-1, drop_partial=True)


def test_zero_patch_size_rejected():
    with pytest.raises(ValueError, match="positive"):
        tile_positions(64, 64, patch_size=0, overlap=0, drop_partial=True)


def test_tiles_carry_correct_spatial_position():
    """Decode each tile's colour back to the grid cell it should have come from."""
    image = positioned_grid(tile_size=8, rows=3, cols=4)
    tiles = extract_tiles(
        image,
        tissue_mask=None,
        config=TilingConfig(
            patch_size=8, overlap=0, downsample=1, min_tissue_fraction=0.0
        ),
    )
    assert len(tiles) == 12
    for tile in tiles:
        r, c, marker = tile.image[0, 0]
        assert marker == 7
        assert (int(r) - 1, int(c) - 1) == (tile.row, tile.col)
        assert (tile.y, tile.x) == (tile.row * 8, tile.col * 8)
        # A tile must be internally uniform, or the crop straddled a boundary.
        assert len(np.unique(tile.image.reshape(-1, 3), axis=0)) == 1


def test_source_coordinates_account_for_downsampling():
    image = positioned_grid(tile_size=8, rows=2, cols=2)  # 16x16
    tiles = extract_tiles(
        image,
        tissue_mask=None,
        config=TilingConfig(
            patch_size=4, overlap=0, downsample=2, min_tissue_fraction=0.0
        ),
    )
    assert len(tiles) == 4
    for tile in tiles:
        assert tile.source_y == tile.y * 2
        assert tile.source_x == tile.x * 2
        assert tile.source_y < image.shape[0]
        assert tile.source_x < image.shape[1]


def test_downsample_preserves_content_positions():
    image = positioned_grid(tile_size=8, rows=2, cols=2)
    small = downsample(image, 2)
    assert small.shape == (8, 8, 3)
    np.testing.assert_array_equal(small[0, 0], image[0, 0])
    np.testing.assert_array_equal(small[4, 4], image[8, 8])


def test_downsample_factor_one_is_identity():
    image = positioned_grid(tile_size=4, rows=2, cols=2)
    np.testing.assert_array_equal(downsample(image, 1), image)


def test_downsample_rejects_zero_factor():
    with pytest.raises(ValueError, match=">= 1"):
        downsample(np.zeros((4, 4, 3), dtype=np.uint8), 0)


def test_background_tiles_are_skipped():
    rgb, mask = synthetic_patch(size=64)
    tiles = extract_tiles(
        rgb,
        tissue_mask=mask,
        config=TilingConfig(
            patch_size=16, overlap=0, downsample=1, min_tissue_fraction=0.9
        ),
    )
    assert tiles
    assert all(t.tissue_fraction >= 0.9 for t in tiles)
    # The corner tile is pure glass and must not survive.
    assert all((t.row, t.col) != (0, 0) for t in tiles)


def test_all_tiles_kept_when_threshold_is_zero():
    rgb, mask = synthetic_patch(size=64)
    tiles = extract_tiles(
        rgb,
        tissue_mask=mask,
        config=TilingConfig(
            patch_size=16, overlap=0, downsample=1, min_tissue_fraction=0.0
        ),
    )
    assert len(tiles) == 16


def test_mismatched_mask_shape_raises():
    rgb, _ = synthetic_patch(size=32)
    with pytest.raises(ValueError, match="does not match"):
        extract_tiles(rgb, tissue_mask=np.ones((8, 8), dtype=bool))


def test_tiles_are_all_requested_size():
    rgb, mask = synthetic_patch(size=64)
    tiles = extract_tiles(
        rgb,
        tissue_mask=mask,
        config=TilingConfig(
            patch_size=16, overlap=0, downsample=1, min_tissue_fraction=0.0
        ),
    )
    assert all(t.image.shape == (16, 16, 3) for t in tiles)
    assert all(isinstance(t, Tile) for t in tiles)
