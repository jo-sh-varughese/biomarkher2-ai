"""Run Phase 1 preprocessing and the Phase 2 model over a single patch.

This is the piece the viewer sits on top of. It is deliberately separate from
the HTTP layer so it can be tested without a server, and so Phase 3 can call it
per tile when it stitches whole slides.

Two things it does that are not incidental:

* It runs the **classical DAB thresholder beside the model, every time**. That
  thresholder produced the targets the model was trained on, so the model
  agreeing with it is not evidence of anything -- which is exactly why a viewer
  that showed only the model would be misleading. Showing both, always, keeps
  the control in front of whoever is looking.
* It returns **tissue-area** percentages and says so in the field name. CAP's
  percentages are of *tumour cells*. These are not that, and the two diverge
  whenever stroma content varies.

Nothing here produces a HER2 score. It produces measurements for a pathologist
to read.
"""

from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from evaluation.conformal import (
    PSEUDO_LABEL_CALIBRATION_CAVEAT,
    checkpoint_fingerprint,
    hinge_scores,
    load_calibrator,
    prediction_mask,
)
from evaluation.stain_shift import patch_stain_descriptor
from models import prepare_pixel_array, select_architecture
from preprocessing.baseline import CLASS_NAMES, NUM_CLASSES, area_distribution
from preprocessing.config import PreprocessingConfig
from preprocessing.pipeline import PreprocessingPipeline
from training.config import TrainingConfig

# Colour-blind-safe: a neutral pair for the two unstained classes and a
# single-hue orange ramp that also increases monotonically in darkness, so the
# ordering survives greyscale printing and both common forms of colour vision
# deficiency.
INTENSITY_COLORS: dict[int, str] = {
    0: "#f0f0f0",
    1: "#cfd8dc",
    2: "#ffd699",
    3: "#e08214",
    4: "#8c3d04",
}

MODEL_LIMITATION = (
    "This model's moderate (2+) prediction is real but imperfect: on its "
    "validation set it reaches 0.59 IoU, 73% precision, 76% recall for that "
    "class (see PHASE5.md) -- a large improvement over an earlier SegFormer "
    "model that never predicted it at all (IoU 0.0001), but still means "
    "roughly a quarter of true 2+ area is missed or over-called. 2+ is the "
    "category that decides reflex FISH testing, so any 2+ percentage below "
    "still warrants reading the baseline column beside it, not treating this "
    "number as final."
)

TARGET_CAVEAT = (
    "The model was trained on DAB optical-density thresholds, not on "
    "pathologist annotations. Where it agrees with the baseline column, that "
    "is agreement with the rule it was trained to imitate -- not evidence of "
    "clinical accuracy."
)

DENOMINATOR_CAVEAT = (
    "Percentages are of TISSUE AREA, not of tumour cells. CAP/ASCO scoring is "
    "defined on the percentage of tumour cells showing membrane staining. "
    "These two diverge whenever stroma content varies, and they are not "
    "interchangeable."
)

NOT_A_SCORE = (
    "This is a pre-scoring measurement aid. It does not assign a HER2 score "
    "and is not a diagnosis. A pathologist assigns the score."
)

# Deliberately shares no colour with INTENSITY_COLORS. The ambiguity panel
# answers a different question ("how sure was the model here") from the
# other four panels ("what class is here"), and a palette overlap would let
# it be misread as a fifth intensity class at a glance -- exactly the
# confusion prediction-set size vs. class identity must never create.
AMBIGUITY_COLORS: dict[int, str] = {
    0: "#f0f0f0",  # excluded (non-tissue) -- same neutral as INTENSITY_COLORS[0]
    1: "#c9d6d9",  # confident: prediction set is a singleton
    2: "#b3286e",  # ambiguous: prediction set size != 1 (empty or multi-class)
}

STALE_CALIBRATION_CAVEAT = (
    "This calibration artifact was computed against a different checkpoint "
    "than the one currently loaded. The ambiguity numbers below may not "
    "reflect the model actually running -- re-run "
    "scripts/calibrate_conformal.py against this checkpoint before trusting "
    "them."
)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


PALETTE = np.array(
    [_hex_to_rgb(INTENSITY_COLORS[c]) for c in range(NUM_CLASSES)], dtype=np.uint8
)

AMBIGUITY_PALETTE = np.array(
    [_hex_to_rgb(AMBIGUITY_COLORS[c]) for c in range(3)], dtype=np.uint8
)


def colorize(classes: np.ndarray) -> np.ndarray:
    """Class-index map -> RGB, using the palette above."""
    return PALETTE[np.clip(classes, 0, NUM_CLASSES - 1)]


def overlay(rgb: np.ndarray, classes: np.ndarray, alpha: float = 0.55) -> np.ndarray:
    """Blend the class map over the image, leaving background untouched.

    Background stays as the original pixels rather than being painted, so the
    viewer can still see what the tissue detector excluded and disagree with
    it. A fully painted overlay hides its own mistakes.
    """
    tinted = colorize(classes).astype(np.float32)
    base = rgb.astype(np.float32)
    weight = np.where(classes[..., None] == 0, 0.0, alpha)
    return (base * (1 - weight) + tinted * weight).round().astype(np.uint8)


def overlay_ambiguity(rgb: np.ndarray, status: np.ndarray, alpha: float = 0.55) -> np.ndarray:
    """Blend a prediction-set-size status map over the image.

    ``status`` is 0 (excluded / non-tissue), 1 (confident -- the calibrated
    prediction set is a singleton) or 2 (ambiguous -- empty or multi-class).
    Mirrors :func:`overlay`'s exact discipline: excluded pixels (status 0)
    are left as the original pixels, not painted, for the same reason
    background is left unpainted there -- so a viewer can still see what was
    excluded from the denominator, here the same tissue mask every other
    percentage in this module already uses.
    """
    tinted = AMBIGUITY_PALETTE[np.clip(status, 0, 2)].astype(np.float32)
    base = rgb.astype(np.float32)
    weight = np.where(status[..., None] == 0, 0.0, alpha)
    return (base * (1 - weight) + tinted * weight).round().astype(np.uint8)


def to_data_uri(array: np.ndarray, max_side: int = 640) -> str:
    """PNG data URI, downscaled for transport only."""
    image = Image.fromarray(array)
    if max(image.size) > max_side:
        scale = max_side / max(image.size)
        new = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        # NEAREST: these are class maps as often as they are photographs, and
        # resampling a class map invents intensity classes that were never
        # predicted.
        image = image.resize(new, Image.Resampling.NEAREST)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def percentages(classes: np.ndarray) -> dict[str, float]:
    """Tissue-area percentage per class name. Background is excluded."""
    distribution = area_distribution(classes)
    return {
        CLASS_NAMES[c]: round(100 * distribution.fractions.get(c, 0.0), 2)
        for c in range(1, NUM_CLASSES)
    }


@dataclass
class PatchAnalysis:
    patch_id: str
    width: int
    height: int
    tissue_percent: float
    model_percentages: dict[str, float]
    baseline_percentages: dict[str, float]
    images: dict[str, str] = field(default_factory=dict)
    disagreement_percent: float = 0.0
    conformal: dict | None = None
    """None when no calibration artifact is loaded at all. When a calibrator
    IS loaded, always a dict with at least "available": True -- see
    Analyzer._conformal_fields for the rest of its shape. Never a field the
    frontend has to guess is missing vs. present-but-empty."""

    def to_dict(self) -> dict:
        conformal = self.conformal or {"available": False}
        caveats = {
            "not_a_score": NOT_A_SCORE,
            "model_limitation": MODEL_LIMITATION,
            "targets": TARGET_CAVEAT,
            "denominator": DENOMINATOR_CAVEAT,
        }
        if conformal.get("available"):
            note = (
                f"Conformal prediction (alpha={conformal['alpha']}): "
                f"{conformal['ambiguous_percent']}% of tissue pixels have an "
                "ambiguous prediction set -- the model's calibrated "
                "confidence does not narrow to exactly one class there. "
                f"{conformal['calibration_caveat']}"
            )
            if conformal.get("stale_calibration"):
                note += " " + STALE_CALIBRATION_CAVEAT
            caveats["conformal"] = note
        return {
            "patch_id": self.patch_id,
            "width": self.width,
            "height": self.height,
            "tissue_percent": self.tissue_percent,
            "model_percentages": self.model_percentages,
            "baseline_percentages": self.baseline_percentages,
            "disagreement_percent": self.disagreement_percent,
            "images": self.images,
            "conformal": conformal,
            "caveats": caveats,
        }


class Analyzer:
    """Loads the checkpoint once and analyses patches against it.

    Architecture-agnostic via ``models.select_architecture`` /
    ``models.prepare_pixel_array`` -- this class does not assume RGB-only
    input or hardcode which model module to import, so it loads whatever
    architecture the run's own ``resolved_config.yaml`` says it is. Only
    "unet" exists today (see PHASE5.md), but nothing here would need to
    change if that were no longer true.
    """

    def __init__(
        self,
        run_dir: str | Path,
        training_config: str | Path = "configs/training.yaml",
        preprocessing_config: str | Path = "configs/preprocessing.yaml",
        conformal_alpha: float = 0.10,
    ) -> None:
        self.run_dir = Path(run_dir)
        checkpoint_path = self.run_dir / "best.pt"
        if not checkpoint_path.is_file():
            raise FileNotFoundError(
                f"No checkpoint at {checkpoint_path}. Train a model first: "
                "python scripts/train_phase2.py --config configs/training.yaml"
            )

        self.config = TrainingConfig.from_yaml(training_config)
        self.preprocessing = PreprocessingConfig.from_yaml(preprocessing_config)
        self.pipeline = PreprocessingPipeline(self.preprocessing)

        build_model, self.normalize_batch = select_architecture(self.config.model.architecture)
        self.in_channels = int(self.config.model.in_channels)

        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        self.model = build_model(self.config.model, verbose=False)
        self.model.load_state_dict(checkpoint["model_state"])
        self.model.eval()

        self.checkpoint_epoch = int(checkpoint.get("epoch", -1))
        self.tile_size = int(self.config.model.image_size)
        # Carried into the UI so a screenshot of the viewer always says which
        # run produced it, and under what caveats.
        self.provenance = {
            "run": str(self.run_dir),
            "epoch": self.checkpoint_epoch,
            "architecture": self.config.model.architecture,
            "validation_caveat": checkpoint.get("caveat", ""),
        }

        # Conformal prediction is entirely optional: a checkpoint nobody has
        # run scripts/calibrate_conformal.py against yet must still load and
        # serve every other field exactly as before. A load failure prints a
        # NOTE and disables the feature -- it never blocks server start-up,
        # the same "degrade, don't crash" idiom used everywhere else a run's
        # optional artifact might be missing or malformed.
        self.conformal_alpha = float(conformal_alpha)
        self.calibrator = None
        self.calibration_bandwidth = None
        self.conformal_stale = False
        try:
            loaded = load_calibrator(self.run_dir)
        except Exception as exc:  # noqa: BLE001 - any failure just disables the feature
            print(
                f"NOTE: could not load conformal calibration from {self.run_dir} "
                f"({type(exc).__name__}: {exc}); analyze() will not include "
                "conformal fields."
            )
            loaded = None
        if loaded is not None:
            self.calibrator, self.calibration_bandwidth = loaded
            self.conformal_stale = self._calibration_is_stale(checkpoint_path)

    def _calibration_is_stale(self, checkpoint_path: Path) -> bool:
        """Whether the loaded calibration was computed against a DIFFERENT
        checkpoint than the one just loaded (see scripts/calibrate_conformal.py's
        checkpoint_epoch / checkpoint_fingerprint fields).

        Missing or unreadable identity information is treated as stale rather
        than fresh -- the whole point of this check is to never silently show
        a calibration that might not match the running model, so "cannot
        verify" and "verified different" get the same cautious answer.
        """
        ids_path = self.run_dir / "conformal_calibration_ids.json"
        try:
            ids = json.loads(ids_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return True
        recorded_epoch = ids.get("checkpoint_epoch")
        recorded_fingerprint = ids.get("checkpoint_fingerprint")
        if recorded_epoch is None or recorded_fingerprint is None:
            return True
        current_fingerprint = checkpoint_fingerprint(checkpoint_path)
        return recorded_epoch != self.checkpoint_epoch or recorded_fingerprint != current_fingerprint

    def predict(self, rgb: np.ndarray) -> np.ndarray:
        """Dense class prediction over an image of any size.

        The image is cut into non-overlapping tiles of the size the model was
        trained at and the tiles are placed back where they came from. This is
        a within-patch operation only -- slide-level stitching is Phase 3's,
        and deliberately not done here.
        """
        classes, _probabilities = self._predict_tiles(rgb)
        return classes

    def _predict_tiles(self, rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Shared tiling loop behind both :meth:`predict` and :meth:`analyze`.

        Returns ``(classes, probabilities)`` -- the argmax class map
        :meth:`predict` has always returned, plus the full per-pixel softmax
        distribution (H, W, NUM_CLASSES) that conformal prediction needs.
        Computed together so analyze() gets both from exactly one forward
        pass per tile; before this, analyze() called predict() for the class
        map and would have needed a second, otherwise-identical pass to also
        get probabilities.
        """
        height, width = rgb.shape[:2]
        size = self.tile_size
        prediction = np.zeros((height, width), dtype=np.uint8)
        probabilities = np.zeros((height, width, NUM_CLASSES), dtype=np.float32)
        for top in range(0, height, size):
            for left in range(0, width, size):
                tile = rgb[top : top + size, left : left + size]
                th, tw = tile.shape[:2]
                if th < size or tw < size:
                    # Edge-replicate rather than zero-pad: a black margin is a
                    # strong artificial edge and the model would predict on it.
                    tile = np.pad(
                        tile, ((0, size - th), (0, size - tw), (0, 0)), mode="edge"
                    )
                array = prepare_pixel_array(tile, self.in_channels)
                pixels = torch.from_numpy(np.ascontiguousarray(array))
                pixels = pixels.permute(2, 0, 1).float()[None]
                with torch.no_grad():
                    logits = self.model(self.normalize_batch(pixels))
                    probs = logits.softmax(dim=1)[0].permute(1, 2, 0).numpy()
                classes = probs.argmax(axis=-1).astype(np.uint8)
                prediction[top : top + th, left : left + tw] = classes[:th, :tw]
                probabilities[top : top + th, left : left + tw] = probs[:th, :tw]
        return prediction, probabilities

    def _conformal_fields(
        self, normalized_rgb: np.ndarray, probabilities: np.ndarray, tissue: np.ndarray
    ) -> tuple[dict | None, str | None]:
        """The "conformal" dict and ambiguity-panel data URI for one analysis,
        or ``(None, None)`` if no calibrator is loaded.

        Restricted to tissue pixels, same denominator discipline every other
        percentage in this module follows -- background carries no
        meaningful class, so folding it in would dilute ambiguous_percent
        with pixels the model was never asked to be confident about.

        Unweighted by construction (no test_descriptor/bandwidth passed to
        ``quantile``): HER2_IHC_40X is single-source, and
        evaluation.conformal's own module docstring is explicit that plain
        conformal prediction is what every current run should use until real
        multi-source data justifies switching stain-shift weighting on.
        """
        if self.calibrator is None or not tissue.any():
            return None, None

        tissue_probs = probabilities[tissue]
        scores = hinge_scores(tissue_probs)
        quantiles = {
            c: calib.quantile(self.conformal_alpha) for c, calib in self.calibrator.by_class.items()
        }
        mask = prediction_mask(scores, quantiles)
        set_sizes = mask.sum(axis=1)
        ambiguous_percent = round(100 * float((set_sizes != 1).sum()) / mask.shape[0], 2)

        status = np.zeros(tissue.shape, dtype=np.uint8)
        status[tissue] = np.where(set_sizes == 1, 1, 2).astype(np.uint8)
        ambiguity_image = to_data_uri(overlay_ambiguity(normalized_rgb, status))

        fields = {
            "available": True,
            "alpha": self.conformal_alpha,
            "ambiguous_percent": ambiguous_percent,
            "weighted": False,
            "calibration_caveat": PSEUDO_LABEL_CALIBRATION_CAVEAT,
            "stale_calibration": self.conformal_stale,
        }
        return fields, ambiguity_image

    def analyze(self, rgb: np.ndarray, patch_id: str = "uploaded") -> PatchAnalysis:
        processed = self.pipeline.run(rgb, patch_id=patch_id)
        baseline = processed.intensity
        predicted, probabilities = self._predict_tiles(processed.normalized)
        # The model has no tissue detector of its own; restrict it to the same
        # tissue mask the baseline uses, or the two columns would be measured
        # over different denominators and could not be compared.
        predicted = np.where(processed.tissue_mask, predicted, 0).astype(np.uint8)

        tissue = processed.tissue_mask
        disagree = (predicted != baseline) & tissue
        tissue_pixels = int(tissue.sum())

        conformal, ambiguity_image = self._conformal_fields(
            processed.normalized, probabilities, tissue
        )

        images = {
            "original": to_data_uri(processed.original),
            "tissue": to_data_uri(
                np.where(tissue[..., None], processed.original, 245).astype(np.uint8)
            ),
            "model": to_data_uri(overlay(processed.normalized, predicted)),
            "baseline": to_data_uri(overlay(processed.normalized, baseline)),
        }
        if ambiguity_image is not None:
            images["ambiguity"] = ambiguity_image

        return PatchAnalysis(
            patch_id=patch_id,
            width=int(rgb.shape[1]),
            height=int(rgb.shape[0]),
            tissue_percent=round(100 * tissue_pixels / max(1, tissue.size), 2),
            model_percentages=percentages(predicted),
            baseline_percentages=percentages(baseline),
            disagreement_percent=round(
                100 * int(disagree.sum()) / max(1, tissue_pixels), 2
            ),
            images=images,
            conformal=conformal,
        )
