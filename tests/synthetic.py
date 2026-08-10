"""Deterministic synthetic IHC-like images for tests.

Tests must not depend on the 1.5 GB dataset being unpacked, and they must not
depend on a random seed behaving the same across numpy versions. These
generators build images by *construction* in optical-density space: we choose
the stain concentrations we want, then render the RGB that would produce
them. That makes the expected deconvolution output known in advance, which is
what lets the stain tests assert real numbers rather than just shapes.
"""

from __future__ import annotations

import numpy as np

from preprocessing.stains import build_stain_matrix, od_to_rgb


def render_from_concentrations(
    hematoxylin: np.ndarray,
    dab: np.ndarray,
    background_intensity: float = 255.0,
) -> np.ndarray:
    """Render an RGB image from known per-pixel stain concentrations.

    This is the exact forward model that :func:`deconvolve` inverts, so
    deconvolving the result must recover the inputs.
    """
    h = np.asarray(hematoxylin, dtype=np.float64)
    d = np.asarray(dab, dtype=np.float64)
    if h.shape != d.shape:
        raise ValueError("Concentration maps must have the same shape")
    matrix = build_stain_matrix()
    concentrations = np.stack([h, d, np.zeros_like(h)], axis=-1)
    od = concentrations @ matrix
    return od_to_rgb(od, background_intensity)


def synthetic_patch(
    size: int = 64,
    dab_level: float = 0.6,
    hematoxylin_level: float = 0.4,
    tissue_box: tuple[int, int, int, int] | None = None,
    background_intensity: float = 255.0,
) -> tuple[np.ndarray, np.ndarray]:
    """A white-background image with one rectangular stained tissue region.

    Returns (rgb, expected_tissue_mask). Outside the box both stain
    concentrations are zero, which renders as pure white -- i.e. bare slide
    glass, with zero saturation, which is what tissue detection must reject.
    """
    if tissue_box is None:
        margin = max(1, size // 4)
        tissue_box = (margin, margin, size - margin, size - margin)
    top, left, bottom, right = tissue_box

    h = np.zeros((size, size), dtype=np.float64)
    d = np.zeros((size, size), dtype=np.float64)
    h[top:bottom, left:right] = hematoxylin_level
    d[top:bottom, left:right] = dab_level

    mask = np.zeros((size, size), dtype=bool)
    mask[top:bottom, left:right] = True
    return render_from_concentrations(h, d, background_intensity), mask


def graded_patch(size: int = 64, background_intensity: float = 255.0) -> np.ndarray:
    """Tissue whose DAB concentration increases in four vertical bands.

    Band DAB concentrations are 0.0, 0.35, 0.65 and 0.95, chosen to fall
    inside the default negative/weak/moderate/strong threshold bands.
    """
    h = np.full((size, size), 0.35, dtype=np.float64)
    d = np.zeros((size, size), dtype=np.float64)
    band = size // 4
    for index, level in enumerate((0.0, 0.35, 0.65, 0.95)):
        start = index * band
        stop = (index + 1) * band if index < 3 else size
        d[:, start:stop] = level
    return render_from_concentrations(h, d, background_intensity)


def positioned_grid(tile_size: int = 8, rows: int = 3, cols: int = 4) -> np.ndarray:
    """An image where each tile carries a unique, decodable colour.

    Tile (r, c) is filled with the constant colour (r + 1, c + 1, 7). Tiling
    can therefore be verified by decoding a tile's own pixels back into the
    grid position it came from -- an off-by-one in the coordinate maths shows
    up as a mismatch rather than as a plausible-looking image.
    """
    image = np.zeros((rows * tile_size, cols * tile_size, 3), dtype=np.uint8)
    for r in range(rows):
        for c in range(cols):
            image[
                r * tile_size : (r + 1) * tile_size,
                c * tile_size : (c + 1) * tile_size,
            ] = (r + 1, c + 1, 7)
    return image
