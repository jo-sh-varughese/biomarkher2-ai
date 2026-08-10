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
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from models.segformer_seg import build_model, normalize_batch
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
    "This model does not reliably predict the moderate (2+) class. On its "
    "validation set it assigned 2+ to 253 pixels out of 21 million (IoU "
    "0.0001); pixels the threshold baseline calls 2+ are called weak (1+) or "
    "strong (3+) instead. Any 2+ area percentage below is therefore not "
    "trustworthy, and 2+ is the category that decides reflex FISH testing. "
    "Read the baseline column beside it."
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


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


PALETTE = np.array(
    [_hex_to_rgb(INTENSITY_COLORS[c]) for c in range(NUM_CLASSES)], dtype=np.uint8
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

    def to_dict(self) -> dict:
        return {
            "patch_id": self.patch_id,
            "width": self.width,
            "height": self.height,
            "tissue_percent": self.tissue_percent,
            "model_percentages": self.model_percentages,
            "baseline_percentages": self.baseline_percentages,
            "disagreement_percent": self.disagreement_percent,
            "images": self.images,
            "caveats": {
                "not_a_score": NOT_A_SCORE,
                "model_limitation": MODEL_LIMITATION,
                "targets": TARGET_CAVEAT,
                "denominator": DENOMINATOR_CAVEAT,
            },
        }


class Analyzer:
    """Loads the checkpoint once and analyses patches against it."""

    def __init__(
        self,
        run_dir: str | Path,
        training_config: str | Path = "configs/training.yaml",
        preprocessing_config: str | Path = "configs/preprocessing.yaml",
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
            "checkpoint": self.config.model.checkpoint,
            "validation_caveat": checkpoint.get("caveat", ""),
        }

    def predict(self, rgb: np.ndarray) -> np.ndarray:
        """Dense class prediction over an image of any size.

        The image is cut into non-overlapping tiles of the size the model was
        trained at and the tiles are placed back where they came from. This is
        a within-patch operation only -- slide-level stitching is Phase 3's,
        and deliberately not done here.
        """
        height, width = rgb.shape[:2]
        size = self.tile_size
        prediction = np.zeros((height, width), dtype=np.uint8)
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
                pixels = torch.from_numpy(np.ascontiguousarray(tile))
                pixels = pixels.permute(2, 0, 1).float()[None] / 255.0
                with torch.no_grad():
                    logits = self.model(normalize_batch(pixels))
                classes = logits.argmax(dim=1)[0].numpy().astype(np.uint8)
                prediction[top : top + th, left : left + tw] = classes[:th, :tw]
        return prediction

    def analyze(self, rgb: np.ndarray, patch_id: str = "uploaded") -> PatchAnalysis:
        processed = self.pipeline.run(rgb, patch_id=patch_id)
        baseline = processed.intensity
        predicted = self.predict(processed.normalized)
        # The model has no tissue detector of its own; restrict it to the same
        # tissue mask the baseline uses, or the two columns would be measured
        # over different denominators and could not be compared.
        predicted = np.where(processed.tissue_mask, predicted, 0).astype(np.uint8)

        tissue = processed.tissue_mask
        disagree = (predicted != baseline) & tissue
        tissue_pixels = int(tissue.sum())

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
            images={
                "original": to_data_uri(processed.original),
                "tissue": to_data_uri(
                    np.where(tissue[..., None], processed.original, 245).astype(np.uint8)
                ),
                "model": to_data_uri(overlay(processed.normalized, predicted)),
                "baseline": to_data_uri(overlay(processed.normalized, baseline)),
            },
        )
