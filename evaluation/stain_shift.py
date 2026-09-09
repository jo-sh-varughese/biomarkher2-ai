"""Shared stain-shift primitives: a numeric descriptor of a patch's stain,
and the kernel that turns a distance between descriptors into a similarity
weight.

Used by two things that are otherwise unrelated:

* :mod:`evaluation.conformal`, which downweights calibration evidence whose
  stain looks unlike the test patch's (Objective 2: stain-shift-weighted
  conformal prediction).
* :mod:`evaluation.stain_variation`, which reports how much this descriptor
  actually varies across the dataset's provenance groups (Objective 1:
  adaptive stain-vector analysis).

Sharing this module means the same number means the same thing in both
places -- a stain-shift weight computed for calibration and a stain
"distance" reported in the variation summary are the same quantity, not two
similar-looking ones that happen to disagree.
"""

from __future__ import annotations

import numpy as np

from preprocessing.stains import estimate_macenko_stain_matrix


def stain_descriptor(stain_matrix: np.ndarray) -> np.ndarray:
    """Flatten a stain matrix's two real rows into one 6-vector.

    Only the haematoxylin and DAB rows (0 and 1) carry stain information --
    row 2 is the residual direction built by
    :func:`preprocessing.stains.build_stain_matrix` to make the matrix
    invertible, not a property of the sample, so it is dropped here.
    """
    matrix = np.asarray(stain_matrix, dtype=np.float64)
    if matrix.shape != (3, 3):
        raise ValueError(f"Expected a 3x3 stain matrix, got shape {matrix.shape}")
    return matrix[:2].reshape(-1)


def patch_stain_descriptor(
    rgb: np.ndarray,
    tissue_mask: np.ndarray | None = None,
    alpha: float = 1.0,
    beta: float = 0.15,
    background_intensity: float = 255.0,
) -> np.ndarray:
    """Estimate a patch's stain descriptor directly from its pixels.

    Thin wrapper around
    :func:`preprocessing.stains.estimate_macenko_stain_matrix` so callers
    that only want the descriptor do not need to import both modules and
    remember to compose them the same way every time.
    """
    matrix = estimate_macenko_stain_matrix(
        rgb,
        tissue_mask=tissue_mask,
        alpha=alpha,
        beta=beta,
        background_intensity=background_intensity,
    )
    return stain_descriptor(matrix)


def descriptor_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Euclidean distance between two stain descriptors."""
    return float(
        np.linalg.norm(np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64))
    )


def gaussian_kernel_weights(
    calibration_descriptors: np.ndarray,
    test_descriptor: np.ndarray,
    bandwidth: float,
) -> np.ndarray:
    """Similarity weight for each calibration descriptor against one test point.

    ``weight_i = exp(-||d_i - d_test||^2 / (2 * bandwidth^2))``, in (0, 1].
    A calibration descriptor identical to the test descriptor gets weight 1;
    weight decays smoothly as the stain estimate diverges.

    This is a similarity heuristic, not a fitted likelihood ratio between a
    source and target stain distribution -- computing that ratio would need
    a model of both distributions, which nothing here has. It is a
    deliberately simple, inspectable proxy for "how much does this
    calibration example's stain look like the one being predicted on", used
    exactly where :func:`evaluation.conformal.weighted_quantile` needs a
    weight, and documented as an approximation there too.

    ``bandwidth`` must be positive; :func:`median_bandwidth` gives a
    reasonable default derived from the calibration set itself.
    """
    if bandwidth <= 0:
        raise ValueError(f"bandwidth must be positive, got {bandwidth}")
    descriptors = np.asarray(calibration_descriptors, dtype=np.float64)
    test = np.asarray(test_descriptor, dtype=np.float64)
    if descriptors.ndim != 2 or descriptors.shape[1] != test.shape[-1]:
        raise ValueError(
            f"Expected calibration descriptors shaped (n, {test.shape[-1]}), "
            f"got {descriptors.shape}"
        )
    sq_dist = np.sum((descriptors - test[None, :]) ** 2, axis=1)
    return np.exp(-sq_dist / (2.0 * bandwidth**2))


def median_bandwidth(descriptors: np.ndarray, max_samples: int = 500, seed: int = 0) -> float:
    """The median pairwise distance among a set of descriptors.

    A standard default bandwidth for a Gaussian kernel (the "median trick"):
    it scales the kernel to the data's own spread rather than requiring a
    number to be picked by hand. Falls back to 1.0 when fewer than two
    distinct descriptors are given, since no pairwise distance exists to
    measure -- a single point carries no scale information to derive a
    bandwidth from.

    Computed from at most ``max_samples`` DISTINCT rows of ``descriptors``.
    Callers routinely pass one descriptor per calibration PIXEL, where many
    pixels share an identical descriptor -- every tissue pixel of one source
    tile does, by construction (see evaluation.conformal's calibration
    contract). Deduplicating first means the pairwise computation below
    scales with the number of distinct tiles, not the number of pixels,
    which can differ by several orders of magnitude -- a naive pairwise
    matrix over a few million pixel-rows does not fit in memory. A further
    random subsample caps the cost when even the distinct count is large;
    the median of a subsample is a standard, well-behaved estimate of the
    population median for this purpose (a heuristic kernel bandwidth, not a
    quantity that needs to be exact).
    """
    array = np.asarray(descriptors, dtype=np.float64)
    if array.shape[0] < 2:
        return 1.0
    unique = np.unique(array, axis=0)
    if unique.shape[0] < 2:
        return 1.0
    if unique.shape[0] > max_samples:
        rng = np.random.default_rng(seed)
        unique = unique[rng.choice(unique.shape[0], size=max_samples, replace=False)]
    diffs = unique[:, None, :] - unique[None, :, :]
    dists = np.sqrt(np.sum(diffs**2, axis=-1))
    upper = dists[np.triu_indices(unique.shape[0], k=1)]
    median = float(np.median(upper))
    return median if median > 1e-8 else 1.0
