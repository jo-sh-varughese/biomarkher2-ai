"""Configuration dataclasses for Phase 2 training.

Same discipline as :mod:`preprocessing.config`: plain dataclasses + YAML, no
Hydra, and unknown keys are rejected loudly so that a typo cannot silently
change what was run.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from preprocessing.config import build_config


@dataclass
class SplitConfig:
    """How patches are divided into fit / validation / held-out sets.

    See :mod:`training.splits` for why this is not a grouped split in the
    sense the project brief asks for, and what is done instead.
    """

    holdout_by: str = "filename_origin"
    """How the held-out boundary is drawn: "filename_origin" or "directory".

    Defaults to the filename token. The train/ and test/ directories were
    measured to cross it in both directions -- 78% of the files in test/ are
    named _train_ -- so the directory layout is a re-packaging rather than a
    split, and holding out test/ would leak. See :mod:`training.splits`."""

    holdout_value: str = "test"
    """The value of that key whose patches are never trained on."""

    val_fraction: float = 0.15
    """Fraction of the fit split held back for validation."""

    stratify: bool = True
    """Keep the class distribution of the validation set matched to the fit
    set. Necessary here because the 2+ class is scarce."""

    seed: int = 20260805
    """Fixed so that a rerun reproduces the same split exactly."""

    require_all_classes: bool = True
    """Refuse to emit a split where any intensity class is missing from a
    side. A silently class-incomplete split produces metrics that look fine
    and mean nothing."""


@dataclass
class ModelConfig:
    checkpoint: str = "nvidia/segformer-b0-finetuned-ade-512-512"
    """Base checkpoint. B0 (MiT-B0) is the smallest SegFormer variant, chosen
    because Phase 2 has to be runnable on CPU."""

    num_classes: int = 5
    image_size: int = 512
    """Input size fed to the model. The dataset is 1024 at 40x, downsampled by
    2 to an effective 20x -- see TilingConfig.downsample."""

    pretrained: bool = True
    """If False, build from config only. Used by tests so they never touch the
    network."""


@dataclass
class LossConfig:
    cross_entropy_weight: float = 1.0
    dice_weight: float = 0.5
    """Dice is on by default. The class distribution here is severely skewed
    -- background and negative dominate every patch -- and plain CE lets a
    model score well while never predicting the strong class at all."""

    # A list of NUM_CLASSES floats, or the string "auto" to derive
    # inverse-frequency weights from the fit set's own pixel counts. "auto" is
    # resolved to the concrete list before training and written back into
    # resolved_config.yaml, so a run is always reproducible from its artifact
    # rather than from whatever data happened to be cached at the time.
    class_weights: list[float] | str | None = None
    """Optional per-class CE weights. None means uniform."""

    ignore_index: int = -100
    label_smoothing: float = 0.0
    dice_smooth: float = 1.0


@dataclass
class OptimConfig:
    learning_rate: float = 6e-5
    weight_decay: float = 0.01
    epochs: int = 8
    batch_size: int = 2
    """Small by necessity: CPU training with 512x512 inputs."""

    grad_accum_steps: int = 4
    """Effective batch = batch_size * grad_accum_steps, without the memory."""

    warmup_fraction: float = 0.05
    max_grad_norm: float = 1.0
    num_workers: int = 0
    """0 on Windows: worker processes re-import and re-spawn expensively, and
    the dataset is already cached to disk as decoded arrays."""


@dataclass
class DataConfig:
    patch_root: str = "data/raw"
    cache_root: str = "data/cache/pseudo_labels"
    """Where scripts/build_pseudo_labels.py writes precomputed targets."""

    max_fit_patches: int | None = None
    """Cap on training patches, for smoke runs. None means use everything."""

    max_val_patches: int | None = None
    max_holdout_patches: int | None = None
    augment: bool = True
    """Flips and 90-degree rotations only. No colour jitter: it would perturb
    the DAB optical densities that define the labels."""


@dataclass
class TrainingConfig:
    split: SplitConfig = field(default_factory=SplitConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    loss: LossConfig = field(default_factory=LossConfig)
    optim: OptimConfig = field(default_factory=OptimConfig)
    data: DataConfig = field(default_factory=DataConfig)
    output_dir: str = "artifacts/phase2"
    seed: int = 20260805

    _SECTIONS = ("split", "model", "loss", "optim", "data")

    @classmethod
    def from_yaml(cls, path: str | Path) -> "TrainingConfig":
        with open(path, "r", encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh) or {}
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TrainingConfig":
        scalars = {"output_dir", "seed"}
        unknown = set(raw) - set(cls._SECTIONS) - scalars
        if unknown:
            raise ValueError(f"Unknown config section(s): {sorted(unknown)}")
        return cls(
            split=build_config(SplitConfig, raw.get("split")),
            model=build_config(ModelConfig, raw.get("model")),
            loss=build_config(LossConfig, raw.get("loss")),
            optim=build_config(OptimConfig, raw.get("optim")),
            data=build_config(DataConfig, raw.get("data")),
            output_dir=raw.get("output_dir", "artifacts/phase2"),
            seed=raw.get("seed", 20260805),
        )

    def to_yaml(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(asdict(self), fh, sort_keys=False)
