"""Stain normalization and colour deconvolution for H-DAB IHC.

The quantitative claim of this whole project rests on this module: every area
percentage and every intensity class downstream is a function of the DAB
optical density computed here. It is written to be inspectable rather than
clever.

Reference for the deconvolution: Ruifrok & Johnston (2001), "Quantification of
histochemical staining by color deconvolution", Anal Quant Cytol Histol 23(4).
Reference for the normalization: Macenko et al. (2009), and Reinhard et al.
(2001) for the Lab-space variant.
"""

from __future__ import annotations

import numpy as np

from .config import StainConfig

# Ruifrok & Johnston reference vectors for haematoxylin and DAB, as RGB
# absorbance directions. The third row is not a real stain -- it is the
# residual direction, computed as the cross product so the matrix is
# invertible and any signal not explained by the two real stains has
# somewhere to go.
HEMATOXYLIN = np.array([0.650, 0.704, 0.286], dtype=np.float64)
DAB = np.array([0.268, 0.570, 0.776], dtype=np.float64)

# Channel indices into the deconvolved stack.
H_CHANNEL = 0
DAB_CHANNEL = 1
RESIDUAL_CHANNEL = 2


def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def build_stain_matrix(
    stain_one: np.ndarray = HEMATOXYLIN,
    stain_two: np.ndarray = DAB,
) -> np.ndarray:
    """Return a 3x3 stain matrix whose rows are unit absorbance directions.

    The third row is the unit cross product of the first two. If the two
    supplied stains happen to be collinear the cross product vanishes, which
    would make the matrix singular -- that is a genuine error in the inputs,
    so it raises rather than silently producing garbage concentrations.
    """
    first = np.asarray(stain_one, dtype=np.float64)
    second = np.asarray(stain_two, dtype=np.float64)
    residual = np.cross(first, second)
    if np.linalg.norm(residual) < 1e-8:
        raise ValueError(
            "Stain vectors are collinear; cannot build an invertible stain matrix."
        )
    return _normalize_rows(np.vstack([first, second, residual]))


def rgb_to_od(rgb: np.ndarray, background_intensity: float = 255.0) -> np.ndarray:
    """Convert an RGB image to optical density.

    OD = -log10(I / I0). Zero-valued pixels would send this to infinity, so
    intensities are clipped to one quantisation step above zero first.
    """
    array = np.asarray(rgb, dtype=np.float64)
    if array.ndim != 3 or array.shape[-1] != 3:
        raise ValueError(f"Expected an HxWx3 RGB image, got shape {array.shape}")
    clipped = np.clip(array, 1.0, background_intensity)
    return -np.log10(clipped / background_intensity)


def od_to_rgb(od: np.ndarray, background_intensity: float = 255.0) -> np.ndarray:
    """Inverse of :func:`rgb_to_od`, returning uint8 RGB."""
    intensity = background_intensity * np.power(10.0, -np.asarray(od, dtype=np.float64))
    return np.clip(intensity, 0, 255).astype(np.uint8)


def deconvolve(
    rgb: np.ndarray,
    stain_matrix: np.ndarray | None = None,
    background_intensity: float = 255.0,
) -> np.ndarray:
    """Separate an RGB image into per-stain concentration maps.

    Returns an HxWx3 float array of stain concentrations in optical-density
    units, ordered (haematoxylin, DAB, residual). Concentrations are clipped
    at zero: a negative concentration is physically meaningless and, left in,
    would drag down the mean DAB statistics reported in the sanity check.
    """
    matrix = build_stain_matrix() if stain_matrix is None else _normalize_rows(
        np.asarray(stain_matrix, dtype=np.float64)
    )
    od = rgb_to_od(rgb, background_intensity)
    height, width, _ = od.shape
    flat = od.reshape(-1, 3)
    # Rows of `matrix` are stain directions, so concentrations solve
    # od = concentrations @ matrix, i.e. concentrations = od @ inv(matrix).
    concentrations = flat @ np.linalg.pinv(matrix)
    stack = concentrations.reshape(height, width, 3)
    return np.clip(stack, 0.0, None)


def dab_channel(
    rgb: np.ndarray,
    stain_matrix: np.ndarray | None = None,
    background_intensity: float = 255.0,
) -> np.ndarray:
    """Convenience accessor for the DAB optical-density map (the HER2 signal)."""
    return deconvolve(rgb, stain_matrix, background_intensity)[..., DAB_CHANNEL]


def hematoxylin_channel(
    rgb: np.ndarray,
    stain_matrix: np.ndarray | None = None,
    background_intensity: float = 255.0,
) -> np.ndarray:
    """Convenience accessor for the haematoxylin counterstain map."""
    return deconvolve(rgb, stain_matrix, background_intensity)[..., H_CHANNEL]


# --------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------


def estimate_macenko_stain_matrix(
    rgb: np.ndarray,
    tissue_mask: np.ndarray | None = None,
    alpha: float = 1.0,
    beta: float = 0.15,
    background_intensity: float = 255.0,
) -> np.ndarray:
    """Estimate the two dominant stain vectors of an image (Macenko et al.).

    Falls back to the Ruifrok reference matrix when there is not enough
    non-transparent tissue to estimate from -- silently returning a matrix
    fitted to a handful of pixels would be worse than using the reference.
    """
    od = rgb_to_od(rgb, background_intensity).reshape(-1, 3)
    if tissue_mask is not None:
        od = od[np.asarray(tissue_mask, dtype=bool).reshape(-1)]
    strong = od[np.linalg.norm(od, axis=1) > beta] if od.size else od
    if strong.shape[0] < 32:
        return build_stain_matrix()

    # The two stains span a plane; find it by eigendecomposition, then take
    # the extreme angles within that plane as the stain directions.
    _, eigenvectors = np.linalg.eigh(np.cov(strong.T))
    plane = eigenvectors[:, [2, 1]]
    projected = strong @ plane
    angles = np.arctan2(projected[:, 1], projected[:, 0])
    low, high = np.percentile(angles, alpha), np.percentile(angles, 100 - alpha)
    first = plane @ np.array([np.cos(low), np.sin(low)])
    second = plane @ np.array([np.cos(high), np.sin(high)])
    first, second = np.abs(first), np.abs(second)

    # Order the pair so haematoxylin comes first. Haematoxylin is blue-
    # dominant, DAB is red/brown-dominant, so comparing the R-vs-B balance
    # separates them without needing a reference.
    if (first[0] - first[2]) > (second[0] - second[2]):
        first, second = second, first
    try:
        return build_stain_matrix(first, second)
    except ValueError:
        return build_stain_matrix()


def normalize_macenko(
    rgb: np.ndarray,
    config: StainConfig,
    tissue_mask: np.ndarray | None = None,
    target_matrix: np.ndarray | None = None,
    target_concentrations: tuple[float, float] = (1.9705, 1.0308),
) -> np.ndarray:
    """Map an image onto reference stain vectors and concentration scales.

    The default target concentrations are the values used in the reference
    Macenko implementation.
    """
    source_matrix = estimate_macenko_stain_matrix(
        rgb,
        tissue_mask=tissue_mask,
        alpha=config.macenko_alpha,
        beta=config.macenko_beta,
        background_intensity=config.background_intensity,
    )
    target = build_stain_matrix() if target_matrix is None else _normalize_rows(
        np.asarray(target_matrix, dtype=np.float64)
    )

    od = rgb_to_od(rgb, config.background_intensity)
    height, width, _ = od.shape
    concentrations = od.reshape(-1, 3) @ np.linalg.pinv(source_matrix)

    # Rescale each real stain so its 99th percentile matches the target.
    for channel, target_level in enumerate(target_concentrations):
        observed = np.percentile(concentrations[:, channel], 99)
        if observed > 1e-6:
            concentrations[:, channel] *= target_level / observed

    recombined = (concentrations @ target).reshape(height, width, 3)
    return od_to_rgb(recombined, config.background_intensity)


def normalize_reinhard(
    rgb: np.ndarray,
    tissue_mask: np.ndarray | None = None,
    target_mean: tuple[float, float, float] = (68.0, 18.0, -6.0),
    target_std: tuple[float, float, float] = (14.0, 8.0, 5.0),
) -> np.ndarray:
    """Match an image's Lab-space mean and standard deviation to a target.

    Statistics are taken over tissue pixels only when a mask is supplied;
    including the large background region would otherwise dominate the mean
    and effectively normalize the glass rather than the tissue.
    """
    from skimage.color import lab2rgb, rgb2lab

    lab = rgb2lab(np.asarray(rgb, dtype=np.float64) / 255.0)
    if tissue_mask is not None:
        mask = np.asarray(tissue_mask, dtype=bool)
        sample = lab[mask] if mask.any() else lab.reshape(-1, 3)
    else:
        sample = lab.reshape(-1, 3)

    source_mean = sample.mean(axis=0)
    source_std = sample.std(axis=0)
    source_std[source_std < 1e-6] = 1.0

    scaled = (lab - source_mean) / source_std * np.asarray(target_std) + np.asarray(
        target_mean
    )
    return np.clip(lab2rgb(scaled) * 255.0, 0, 255).astype(np.uint8)


def apply_normalization(
    rgb: np.ndarray,
    config: StainConfig,
    tissue_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Dispatch to the configured normalization method."""
    method = (config.normalization or "none").lower()
    if method == "none":
        return np.asarray(rgb, dtype=np.uint8)
    if method == "macenko":
        return normalize_macenko(rgb, config, tissue_mask=tissue_mask)
    if method == "reinhard":
        return normalize_reinhard(rgb, tissue_mask=tissue_mask)
    raise ValueError(
        f"Unknown normalization method {config.normalization!r}; "
        "expected one of 'none', 'macenko', 'reinhard'."
    )
