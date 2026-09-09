"""Conformal prediction over the Phase 2 segmentation model's pixel output.

WHAT THIS GENERALIZES
======================
Pintawong et al. (2025), "Conformal Prediction for Uncertainty Quantification
and Reliable HER2 Status Classification in Breast Cancer IHC Images" (IEEE
Access), applies inductive conformal prediction (Vovk, Gammerman & Shafer,
2005) to a binary (HER2 positive/negative) image-level classifier, using the
hinge nonconformity score s_y(x) = 1 - f_hat(x)_y (their Eq. 2) and a
per-class calibration quantile (their Eq. 3) to build a prediction SET per
image rather than a single point prediction (their Eq. 4).

This module is that same recipe, generalized in two ways:

1. **Multi-class, not binary.** Our model outputs 5 intensity classes, not 2
   HER2 statuses. The hinge score and the per-class quantile generalize
   directly -- Sadinle, Lei & Wasserman (2019), "Least Ambiguous Set-Valued
   Classifiers with Bounded Error Levels", is the multi-class treatment of
   the same construction. Nothing about the calibration recipe below assumes
   two classes.

2. **Pixel-level, not image-level.** The base paper's unit of prediction is
   one IHC image; ours is one pixel, because our model is a segmentation
   network and the pixel is the unit it actually produces a probability
   distribution over. A prediction set is built per pixel and rolled up to a
   patch-level status by the same majority rule the base paper uses to go
   from image-level to case-level (their Table 2) -- see
   :func:`aggregate_patch_status`.

WHAT CALIBRATES AGAINST WHAT
=============================
The base paper calibrates against DISH-confirmed HER2 status: real,
independent ground truth. **We have no such thing.** The only per-pixel
target available anywhere in this project is the DAB-threshold pseudo-label
(see training/pseudo_labels.py), so that is what calibration uses here, and
every function in this module that touches "the true class" is calibrating
against pseudo-labels, not pathologist annotation. A prediction set that
achieves its nominal coverage against pseudo-labels has been shown to be
well-calibrated **against the rule the model was trained to imitate** -- not
against clinical truth. That is the same caveat that already governs every
other Phase 2 metric (see training/pseudo_labels.py, training/splits.py) and
it applies here without exception. See PSEUDO_LABEL_CALIBRATION_CAVEAT.

STAIN-SHIFT WEIGHTING
======================
Plain inductive conformal prediction assumes the calibration set and the
test point are exchangeable. Under genuine cross-institution stain shift
they are not: a calibration set built from one source's staining does not
represent a test patch stained differently elsewhere. :func:`weighted_quantile`
applies weighted conformal prediction (Tibshirani, Barber, Candes & Ramdas,
2019, "Conformal Prediction Under Covariate Shift") using the stain-descriptor
kernel weights from :mod:`evaluation.stain_shift` as a similarity-based proxy
for the covariate-shift likelihood ratio their method calls for.

HER2_IHC_40X IS SINGLE-SOURCE (see configs/preprocessing.yaml: normalization
defaults to "none" for exactly this reason). There is no genuine
cross-institution stain shift in this dataset to correct, so weighting has
nothing real to demonstrate a benefit against here -- it can only be
exercised honestly on deliberately-constructed synthetic shift (see
tests/test_conformal.py) until multi-source data exists. Passing
``test_descriptor=None`` (the default) recovers plain, unweighted inductive
conformal prediction exactly, which is what every current run should use
until real multi-source data justifies switching weighting on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from evaluation.stain_shift import gaussian_kernel_weights, median_bandwidth

PSEUDO_LABEL_CALIBRATION_CAVEAT = (
    "Calibrated against DAB optical-density threshold pseudo-labels, not "
    "pathologist annotations. Coverage guarantees hold against the rule the "
    "model was trained to imitate, not against clinical ground truth. See "
    "training/pseudo_labels.py."
)

AMBIGUOUS = "ambiguous"


# --------------------------------------------------------------------------
# Nonconformity scores and calibration quantiles
# --------------------------------------------------------------------------


def hinge_scores(probabilities: np.ndarray) -> np.ndarray:
    """Nonconformity score per class: ``s_c = 1 - p_c``. Eq. 2, generalized
    from 2 classes to C classes.

    ``probabilities`` is a softmax distribution over the last axis; the
    return value is the same shape.
    """
    array = np.asarray(probabilities, dtype=np.float64)
    if array.shape[-1] < 2:
        raise ValueError(f"Expected at least 2 classes, got shape {array.shape}")
    return 1.0 - array


def weighted_quantile(
    scores: np.ndarray,
    alpha: float,
    weights: np.ndarray | None = None,
) -> float:
    """The (1 - alpha) weighted conformal quantile of calibration scores.

    Unweighted (``weights=None``) this is exactly Eq. 3 of the base paper:
    the ``ceil((n+1)(1-alpha))/n`` empirical quantile, implemented via the
    weighted form with uniform weight 1 per calibration point plus one
    reserved unit of weight for the test point itself -- the standard
    construction that gives inductive conformal prediction its finite-sample
    coverage guarantee (Vovk, Gammerman & Shafer, 2005).

    Weighted (Tibshirani et al., 2019), each calibration score keeps its own
    weight, renormalised together with one reserved test-point weight of
    exactly 1.0. That value is not arbitrary: :func:`evaluation.stain_shift.gaussian_kernel_weights`
    evaluated at zero distance -- a point compared against itself -- returns
    exactly 1, so a weight of 1 for the test point is that same kernel
    applied to itself, keeping the test point's contribution on the same
    scale as every calibration weight rather than an unrelated constant.

    Returns +inf when even every calibration point together does not reach
    (1 - alpha) mass -- meaning there is not enough calibration evidence to
    exclude this class, so the conservative answer is to never exclude it,
    not to guess a threshold from too little data.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    values = np.asarray(scores, dtype=np.float64).reshape(-1)
    if values.size == 0:
        raise ValueError("Cannot calibrate a quantile from zero calibration scores.")

    if weights is None:
        w = np.ones(values.size, dtype=np.float64)
    else:
        w = np.asarray(weights, dtype=np.float64).reshape(-1)
        if w.shape != values.shape:
            raise ValueError(
                f"weights shape {w.shape} does not match scores shape {values.shape}"
            )
        if np.any(w < 0):
            raise ValueError("Weights must be non-negative.")

    total = float(w.sum()) + 1.0  # +1: the test point's own (self-similarity) weight
    if total <= 0:
        return float("inf")

    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = w[order] / total
    cumulative = np.cumsum(sorted_weights)
    reach = np.nonzero(cumulative >= (1.0 - alpha) - 1e-12)[0]
    if reach.size == 0:
        return float("inf")
    return float(sorted_values[reach[0]])


# --------------------------------------------------------------------------
# Per-class calibration
# --------------------------------------------------------------------------


@dataclass
class ClassCalibration:
    """Calibration data for one intensity class, ready to produce a quantile.

    ``scores`` are the hinge nonconformity scores of every calibration pixel
    whose pseudo-label true class equals ``class_index`` (Eq. 3's "computed
    ... separately for each class"). ``stain_descriptors``, if given, is one
    6-vector per score, from the source patch that pixel came from --
    required only when a caller wants stain-shift-weighted quantiles.
    """

    class_index: int
    scores: np.ndarray
    stain_descriptors: np.ndarray | None = None
    n: int = field(init=False)

    def __post_init__(self) -> None:
        self.scores = np.asarray(self.scores, dtype=np.float64).reshape(-1)
        if self.scores.size == 0:
            raise ValueError(
                f"No calibration examples for class {self.class_index}. A class "
                "absent from the calibration set cannot be calibrated -- see "
                "training/splits.py's require_all_classes for the same"
                " requirement elsewhere in this project."
            )
        if self.stain_descriptors is not None:
            self.stain_descriptors = np.asarray(self.stain_descriptors, dtype=np.float64)
            if self.stain_descriptors.shape[0] != self.scores.shape[0]:
                raise ValueError(
                    "stain_descriptors must have one row per calibration score: "
                    f"{self.stain_descriptors.shape[0]} vs {self.scores.shape[0]}"
                )
        self.n = int(self.scores.size)

    def quantile(
        self,
        alpha: float,
        test_descriptor: np.ndarray | None = None,
        bandwidth: float | None = None,
    ) -> float:
        """The calibrated threshold for this class at significance ``alpha``.

        Plain (unweighted) unless both ``test_descriptor`` and ``bandwidth``
        are given AND this calibration was built with stain descriptors --
        omitting either falls back to plain conformal prediction rather than
        raising, so a caller can compute an unweighted baseline and a
        stain-shift-weighted result from the same calibration object.
        """
        if test_descriptor is None or bandwidth is None or self.stain_descriptors is None:
            return weighted_quantile(self.scores, alpha, weights=None)
        weights = gaussian_kernel_weights(self.stain_descriptors, test_descriptor, bandwidth)
        return weighted_quantile(self.scores, alpha, weights=weights)


@dataclass
class ConformalCalibrator:
    """Per-class calibration, and the prediction sets it produces.

    Construct with :meth:`fit`, then call :meth:`prediction_set` (one pixel)
    or :meth:`prediction_sets_batch` (many pixels sharing one test-patch
    stain descriptor, which is the common case -- every pixel of one patch
    shares that patch's single stain estimate).
    """

    by_class: dict[int, ClassCalibration]

    @classmethod
    def fit(
        cls,
        class_scores: dict[int, np.ndarray],
        class_descriptors: dict[int, np.ndarray] | None = None,
    ) -> "ConformalCalibrator":
        descriptors = class_descriptors or {}
        return cls(
            by_class={
                c: ClassCalibration(
                    class_index=c, scores=s, stain_descriptors=descriptors.get(c)
                )
                for c, s in class_scores.items()
            }
        )

    def prediction_set(
        self,
        pixel_probabilities: np.ndarray,
        alpha: float,
        test_descriptor: np.ndarray | None = None,
        bandwidth: float | None = None,
    ) -> set[int]:
        """The prediction set for one pixel's softmax distribution."""
        scores = hinge_scores(pixel_probabilities)
        included = set()
        for c, calibration in self.by_class.items():
            q = calibration.quantile(alpha, test_descriptor=test_descriptor, bandwidth=bandwidth)
            if scores[c] <= q:
                included.add(c)
        return included

    def prediction_sets_batch(
        self,
        probabilities: np.ndarray,
        alpha: float,
        test_descriptor: np.ndarray | None = None,
        bandwidth: float | None = None,
    ) -> list[set[int]]:
        """Prediction sets for an (N, C) batch of pixel softmax rows.

        The per-class quantile is computed once and reused for every pixel
        in the batch, since ``test_descriptor`` -- when given -- is one
        estimate per source patch, not per pixel; recomputing it per pixel
        would be wasted work for an identical answer.
        """
        scores = hinge_scores(probabilities)
        quantiles = {
            c: calib.quantile(alpha, test_descriptor=test_descriptor, bandwidth=bandwidth)
            for c, calib in self.by_class.items()
        }
        return [
            {c for c, q in quantiles.items() if row[c] <= q}
            for row in scores
        ]


# --------------------------------------------------------------------------
# Loading a saved calibration artifact (scripts/calibrate_conformal.py's output)
# --------------------------------------------------------------------------


def checkpoint_fingerprint(checkpoint_path: str | Path) -> dict:
    """A cheap, non-cryptographic identity check for a checkpoint file.

    Size and mtime, not a content hash -- hashing a 50-200 MB checkpoint on
    every server start would be real, avoidable cost for a check that only
    needs to catch "this is obviously a different file", not verify byte-
    for-byte identity. Good enough to catch the case that actually matters:
    a checkpoint retrained or replaced after calibration ran, which a
    silently-reused calibration artifact would otherwise apply to the wrong
    model's probabilities without saying so.
    """
    stat = Path(checkpoint_path).stat()
    return {"size": stat.st_size, "mtime": stat.st_mtime}


def load_calibrator(run_dir: str | Path) -> tuple["ConformalCalibrator", float] | None:
    """Load scripts/calibrate_conformal.py's saved artifact, or None if absent.

    Reads ``<run_dir>/conformal_calibration.npz`` and rebuilds a
    :class:`ConformalCalibrator` from its per-class scores and stain
    descriptors, plus a default Gaussian-kernel bandwidth
    (:func:`evaluation.stain_shift.median_bandwidth` over every calibration
    patch's descriptor) for callers that want the stain-shift-weighted
    quantile rather than the plain one.

    Returns ``None`` -- never raises for a missing file -- so a caller (see
    ``app.analysis.Analyzer``) can treat "no calibration yet" as a normal,
    expected state rather than a startup failure: the live viewer worked with
    zero conformal fields before this artifact existed, and it must keep
    working the same way for a checkpoint nobody has calibrated yet.
    """
    npz_path = Path(run_dir) / "conformal_calibration.npz"
    if not npz_path.is_file():
        return None

    data = np.load(npz_path)
    class_scores: dict[int, np.ndarray] = {}
    class_descriptors: dict[int, np.ndarray] = {}
    all_descriptors: list[np.ndarray] = []
    for key in data.files:
        if not key.startswith("scores_"):
            continue
        class_index = int(key.split("_", 1)[1])
        class_scores[class_index] = data[key]
        descriptor_key = f"descriptors_{class_index}"
        if descriptor_key in data.files:
            class_descriptors[class_index] = data[descriptor_key]
            all_descriptors.append(data[descriptor_key])

    if not class_scores:
        return None

    calibrator = ConformalCalibrator.fit(class_scores, class_descriptors)
    combined = (
        np.concatenate(all_descriptors, axis=0) if all_descriptors else np.zeros((0, 6))
    )
    bandwidth = median_bandwidth(combined)
    return calibrator, bandwidth


# --------------------------------------------------------------------------
# Patch-level aggregation (mirrors the base paper's Table 2)
# --------------------------------------------------------------------------


def aggregate_patch_status(pixel_sets: list[set[int]]) -> int | str:
    """Roll pixel-level prediction sets up to one patch-level status.

    Mirrors the base paper's case-level aggregation (their Table 2): each
    pixel is first reduced to a status -- a definite class if its prediction
    set is a singleton, ``AMBIGUOUS`` otherwise (empty or multi-class) -- and
    the patch's status is whichever definite class occupies a strict
    majority (>50%) of pixels. If no class reaches a majority, the patch is
    ``AMBIGUOUS``, exactly as the paper prefers an ambiguous case-level
    prediction over one assembled from a minority of its pixels.
    """
    if not pixel_sets:
        raise ValueError("Cannot aggregate the status of zero pixels.")
    counts: dict[int, int] = {}
    for s in pixel_sets:
        if len(s) == 1:
            (c,) = tuple(s)
            counts[c] = counts.get(c, 0) + 1
    total = len(pixel_sets)
    if counts:
        best_class, best_count = max(counts.items(), key=lambda kv: kv[1])
        if best_count > total / 2:
            return best_class
    return AMBIGUOUS


# --------------------------------------------------------------------------
# Metrics (Eq. 5-7 of the base paper)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ConformalMetrics:
    miscoverage_rate: float
    """Fraction of prediction sets that do NOT contain the true class. Eq. 5."""

    ambiguity_rate: float
    """Fraction of prediction sets whose size is not exactly 1. Eq. 6."""

    accuracy: float
    """Fraction of SINGLETON predictions that are correct. Eq. 7's
    denominator is "total prediction sets" within whatever group is being
    scored; read here as the accuracy of the predictions the framework was
    actually willing to make, matching the base paper's own framing (Section
    IV.C): 0.0 when every prediction was ambiguous, since there is nothing to
    be accurate about."""

    n: int


def prediction_mask(scores: np.ndarray, quantiles: dict[int, float]) -> np.ndarray:
    """Vectorized form of a batch of prediction sets: an (N, C) boolean array.

    ``mask[i, c]`` is True exactly when class c is in pixel i's prediction
    set -- the same membership :meth:`ConformalCalibrator.prediction_sets_batch`
    returns as a list of Python ``set`` objects, computed instead with numpy
    boolean comparisons.

    This is not a style preference. Building a Python ``set`` per pixel and
    evaluating it in a Python-level loop is the single most expensive step
    in scripts/evaluate_conformal.py at real dataset scale: a single 512x512
    tile can carry a few hundred thousand tissue pixels, multiplied by every
    (alpha, weighted) combination in the evaluation grid, multiplied by every
    test tile. See :func:`evaluate_prediction_mask` and
    :func:`aggregate_patch_status_from_mask` for the counterparts that
    consume this instead of a list of sets.
    """
    array = np.asarray(scores, dtype=np.float64)
    mask = np.zeros(array.shape, dtype=bool)
    for c, q in quantiles.items():
        mask[:, c] = array[:, c] <= q
    return mask


def evaluate_prediction_mask(mask: np.ndarray, true_classes: np.ndarray) -> ConformalMetrics:
    """Vectorized counterpart to :func:`evaluate_prediction_sets`.

    Computes the identical three metrics (Eq. 5-7) from an (N, C) boolean
    membership mask (see :func:`prediction_mask`) instead of a Python list of
    ``set`` objects. Kept as a separate function rather than an overload of
    ``evaluate_prediction_sets`` so the set-based path -- smaller-scale, more
    directly readable, and what every other test in this module exercises --
    stays untouched and easy to trust; :func:`test_prediction_mask_matches_prediction_sets_exactly`
    is the test that ties the two together.
    """
    mask = np.asarray(mask, dtype=bool)
    classes = np.asarray(true_classes, dtype=np.int64)
    n = mask.shape[0]
    if n == 0:
        raise ValueError("Cannot evaluate metrics over zero predictions.")
    if classes.shape[0] != n:
        raise ValueError("mask and true_classes must have the same length")

    set_sizes = mask.sum(axis=1)
    ambiguous = set_sizes != 1
    contains_true = mask[np.arange(n), classes]
    singleton = ~ambiguous
    n_singleton = int(singleton.sum())
    singleton_correct = int((singleton & contains_true).sum())

    return ConformalMetrics(
        miscoverage_rate=float((~contains_true).sum()) / n,
        ambiguity_rate=float(ambiguous.sum()) / n,
        accuracy=(singleton_correct / n_singleton) if n_singleton else 0.0,
        n=n,
    )


def aggregate_patch_status_from_mask(mask: np.ndarray) -> int | str:
    """Vectorized counterpart to :func:`aggregate_patch_status`.

    ``mask`` is one patch's (n_pixels, C) prediction membership mask (see
    :func:`prediction_mask`), not a list of sets.
    """
    mask = np.asarray(mask, dtype=bool)
    total = mask.shape[0]
    if total == 0:
        raise ValueError("Cannot aggregate the status of zero pixels.")

    singleton = mask.sum(axis=1) == 1
    if not singleton.any():
        return AMBIGUOUS
    # argmax on a singleton row is unambiguous: exactly one True outranks
    # every False, so it returns that column regardless of tie-breaking.
    singleton_classes = np.argmax(mask[singleton], axis=1)
    counts = np.bincount(singleton_classes, minlength=mask.shape[1])
    best_class = int(np.argmax(counts))
    if counts[best_class] > total / 2:
        return best_class
    return AMBIGUOUS


def evaluate_prediction_sets(
    pixel_sets: list[set[int]], true_classes: list[int]
) -> ConformalMetrics:
    """Compute miscoverage rate, ambiguity rate and singleton accuracy."""
    if len(pixel_sets) != len(true_classes):
        raise ValueError("pixel_sets and true_classes must be the same length")
    n = len(pixel_sets)
    if n == 0:
        raise ValueError("Cannot evaluate metrics over zero predictions.")

    missed = sum(1 for s, y in zip(pixel_sets, true_classes) if y not in s)
    ambiguous = sum(1 for s in pixel_sets if len(s) != 1)
    singleton_correct = sum(
        1 for s, y in zip(pixel_sets, true_classes) if len(s) == 1 and y in s
    )
    n_singleton = n - ambiguous

    return ConformalMetrics(
        miscoverage_rate=missed / n,
        ambiguity_rate=ambiguous / n,
        accuracy=(singleton_correct / n_singleton) if n_singleton else 0.0,
        n=n,
    )


@dataclass(frozen=True)
class PatchMetrics:
    """Patch-level counterpart to :class:`ConformalMetrics`.

    Computed from statuses (:func:`aggregate_patch_status`'s output), not
    from sets -- a status is a definite class index or ``AMBIGUOUS``, which
    is a different shape from a prediction set and needs a different
    definition of each metric:
    """

    miscoverage_rate: float
    """Fraction of patches whose status is a DEFINITE class that is wrong.
    An ambiguous status is a declined prediction, not a wrong one, and does
    not count here -- matching the base paper's framing that a case referred
    for further testing has not made an incorrect call."""

    ambiguity_rate: float
    """Fraction of patches whose status is ``AMBIGUOUS``."""

    accuracy: float
    """Fraction of DEFINITE predictions that are correct. 0.0 when every
    patch was ambiguous."""

    n: int


def evaluate_patch_statuses(
    statuses: list[int | str], true_classes: list[int]
) -> PatchMetrics:
    """Patch-level metrics from :func:`aggregate_patch_status` output.

    Mirrors the base paper's case-level tables (their Tables 3-5) at the
    level our aggregation actually produces: one status per patch, not a set.
    """
    if len(statuses) != len(true_classes):
        raise ValueError("statuses and true_classes must be the same length")
    n = len(statuses)
    if n == 0:
        raise ValueError("Cannot evaluate metrics over zero patches.")

    ambiguous = sum(1 for s in statuses if s == AMBIGUOUS)
    definite = [(s, y) for s, y in zip(statuses, true_classes) if s != AMBIGUOUS]
    missed = sum(1 for s, y in definite if s != y)
    correct = len(definite) - missed

    return PatchMetrics(
        miscoverage_rate=missed / n,
        ambiguity_rate=ambiguous / n,
        accuracy=(correct / len(definite)) if definite else 0.0,
        n=n,
    )
