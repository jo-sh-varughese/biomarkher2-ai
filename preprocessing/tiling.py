"""Tiling of large images into patches, with explicit coordinate bookkeeping.

Every tile carries the coordinates it came from, in the coordinate frame of
the *original* image rather than the downsampled one. Phase 3 has to stitch
predictions back into a full-slide map, and coordinate-transform errors there
are silent -- the heatmap simply ends up subtly wrong. Keeping the mapping
explicit and tested here is what makes that reconstruction verifiable.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import TilingConfig


@dataclass(frozen=True)
class Tile:
    """One extracted patch and its provenance."""

    image: np.ndarray
    """The patch pixels, HxWx3 uint8."""

    row: int
    """Tile index down the grid (not a pixel coordinate)."""

    col: int
    """Tile index across the grid (not a pixel coordinate)."""

    y: int
    """Top edge of the tile in the downsampled working frame, in pixels."""

    x: int
    """Left edge of the tile in the downsampled working frame, in pixels."""

    source_y: int
    """Top edge in the ORIGINAL image frame, in pixels."""

    source_x: int
    """Left edge in the ORIGINAL image frame, in pixels."""

    tissue_fraction: float
    """Fraction of this tile that is tissue, in [0, 1]."""

    @property
    def size(self) -> int:
        return int(self.image.shape[0])


def downsample(image: np.ndarray, factor: int) -> np.ndarray:
    """Integer-factor downsample by strided subsampling.

    Subsampling rather than averaging is deliberate: averaging would blend
    strongly-stained membrane pixels with unstained cytoplasm and shift the
    optical densities that the intensity classes are defined on.
    """
    if factor < 1:
        raise ValueError(f"Downsample factor must be >= 1, got {factor}")
    if factor == 1:
        return image
    return image[::factor, ::factor]


def tile_positions(
    height: int, width: int, patch_size: int, overlap: int, drop_partial: bool
) -> list[tuple[int, int, int, int]]:
    """Enumerate tile positions as (row, col, y, x).

    Positions are generated on a regular grid with the given stride. This is
    separated from pixel extraction so the geometry can be tested on its own.
    """
    if patch_size <= 0:
        raise ValueError(f"patch_size must be positive, got {patch_size}")
    if overlap < 0:
        raise ValueError(f"overlap must be non-negative, got {overlap}")
    if overlap >= patch_size:
        raise ValueError(
            f"overlap ({overlap}) must be smaller than patch_size ({patch_size})"
        )

    stride = patch_size - overlap
    positions: list[tuple[int, int, int, int]] = []
    row = 0
    y = 0
    while y < height:
        if y + patch_size > height:
            if drop_partial:
                break
            y = max(0, height - patch_size)
        col = 0
        x = 0
        while x < width:
            if x + patch_size > width:
                if drop_partial:
                    break
                x = max(0, width - patch_size)
            positions.append((row, col, y, x))
            if not drop_partial and x + patch_size >= width:
                break
            x += stride
            col += 1
        if not drop_partial and y + patch_size >= height:
            break
        y += stride
        row += 1
    return positions


def extract_tiles(
    image: np.ndarray,
    tissue_mask: np.ndarray | None = None,
    config: TilingConfig | None = None,
) -> list[Tile]:
    """Split an image into tiles, skipping those with too little tissue.

    `tissue_mask` must be in the same frame as `image` (i.e. before any
    downsampling); it is downsampled alongside it.
    """
    cfg = config or TilingConfig()
    array = np.asarray(image)
    if array.ndim != 3 or array.shape[-1] != 3:
        raise ValueError(f"Expected an HxWx3 RGB image, got shape {array.shape}")

    working = downsample(array, cfg.downsample)
    if tissue_mask is not None:
        mask = np.asarray(tissue_mask, dtype=bool)
        if mask.shape[:2] != array.shape[:2]:
            raise ValueError(
                f"Tissue mask shape {mask.shape[:2]} does not match image "
                f"shape {array.shape[:2]}"
            )
        working_mask = downsample(mask, cfg.downsample)
    else:
        working_mask = None

    height, width = working.shape[:2]
    tiles: list[Tile] = []
    for row, col, y, x in tile_positions(
        height, width, cfg.patch_size, cfg.overlap, cfg.drop_partial
    ):
        patch = working[y : y + cfg.patch_size, x : x + cfg.patch_size]
        if working_mask is not None:
            sub = working_mask[y : y + cfg.patch_size, x : x + cfg.patch_size]
            fraction = float(sub.mean()) if sub.size else 0.0
        else:
            fraction = 1.0
        if fraction < cfg.min_tissue_fraction:
            continue
        tiles.append(
            Tile(
                image=patch,
                row=row,
                col=col,
                y=y,
                x=x,
                source_y=y * cfg.downsample,
                source_x=x * cfg.downsample,
                tissue_fraction=fraction,
            )
        )
    return tiles
