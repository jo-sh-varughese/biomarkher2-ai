"""Configuration dataclasses for the BioMarkHER2 preprocessing pipeline.

Plain dataclasses + YAML, no Hydra. Every stage of the pipeline takes its
parameters from here so that a run is fully described by a config file.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import yaml


@dataclass
class TissueConfig:
    """Parameters for tissue / background separation."""

    method: str = "od"
    """One of "od", "saturation", "combined".

    Defaults to "od" (optical density), which is stain-independent. See the
    docstring of :mod:`preprocessing.tissue` for the measurements showing why
    saturation-based detection fails on 40x IHC patches. "saturation" remains
    the better choice for low-magnification whole-slide thumbnails."""

    od_floor: float = 0.04
    """Grey optical density above which a pixel counts as tissue. 0.04
    corresponds to roughly 9% light absorption -- comfortably above sensor
    noise on bare glass, below the density of even pale cytoplasm."""

    otsu_od_ceiling: float = 0.15
    """Upper bound on an Otsu-chosen OD threshold. Prevents Otsu drifting up
    to split stained from unstained tissue on strongly-stained patches."""

    achromatic_floor: float = 0.02
    """Minimum saturation for a pixel to be tissue at all. Rejects perfectly
    grey regions (shadow, dust, out-of-focus artifacts) which absorb light
    but are not stained material."""

    background_intensity: float = 255.0
    """I0 for the optical-density transform. Duplicated from StainConfig so
    that tissue detection stays usable on its own; keep the two in step."""

    # Used when method is "saturation" or "combined".
    saturation_floor: float = 0.05
    """Hard floor on saturation. Below this a pixel is background regardless
    of what Otsu decides -- protects against slides that are almost entirely
    tissue, where Otsu would otherwise split the tissue itself."""

    value_ceiling: float = 0.94
    """Pixels brighter than this are bare slide glass."""

    value_floor: float = 0.06
    """Pixels darker than this are pen marks, dust, or scanning artifacts."""

    min_object_area: int = 512
    """Connected components smaller than this (in pixels) are removed."""

    min_hole_area: int = 512
    """Holes smaller than this are filled."""

    morph_radius: int = 3
    """Radius of the disk used for the closing/opening cleanup."""

    use_otsu: bool = False
    """Whether to refine the cut point with Otsu instead of using the fixed
    floor alone.

    Defaults off, matching configs/preprocessing.yaml. On a patch that is
    mostly tissue -- which every patch in a patch-based dataset is -- Otsu has
    no glass/tissue boundary to find, so it splits the tissue itself along
    whatever the dominant contrast is, which is stain. That is the defect this
    module was rewritten to remove, so the safe behaviour is also the default
    for anyone constructing TissueConfig() directly."""


@dataclass
class StainConfig:
    """Parameters for stain normalization and colour deconvolution."""

    normalization: str = "none"
    """One of "none", "macenko", "reinhard".

    Deliberately defaults to "none": the substitute dataset is single-source,
    so there is no inter-scanner variation to correct, and normalizing would
    silently alter the DAB optical densities that the entire quantitative
    method rests on. Switch this on when genuinely multi-source data arrives.
    """

    background_intensity: float = 255.0
    """I0, the incident light intensity used for the OD transform."""

    macenko_alpha: float = 1.0
    """Percentile (and 100-alpha) used to find robust stain vector angles."""

    macenko_beta: float = 0.15
    """OD threshold below which pixels are treated as transparent."""

    dab_od_weak: float = 0.25
    """DAB optical density above which staining counts as weak (1+)."""

    dab_od_moderate: float = 0.50
    """DAB optical density above which staining counts as moderate (2+)."""

    dab_od_strong: float = 0.80
    """DAB optical density above which staining counts as strong (3+)."""

    def thresholds(self) -> tuple[float, float, float]:
        return (self.dab_od_weak, self.dab_od_moderate, self.dab_od_strong)


@dataclass
class TilingConfig:
    """Parameters for splitting a large image into patches."""

    patch_size: int = 512
    overlap: int = 0
    """Overlap in pixels between adjacent tiles."""

    downsample: int = 2
    """Integer downsample applied before tiling. The substitute dataset is
    1024x1024 at 40x; a downsample of 2 yields 512x512 at an effective 20x,
    which is a sensible working magnification for membrane staining."""

    min_tissue_fraction: float = 0.10
    """Tiles with less tissue than this are skipped as background."""

    drop_partial: bool = True
    """If True, tiles that would run off the image edge are dropped rather
    than zero-padded. Padding would inject fake background into the area
    percentages computed in Phase 3."""


@dataclass
class PreprocessingConfig:
    tissue: TissueConfig = field(default_factory=TissueConfig)
    stain: StainConfig = field(default_factory=StainConfig)
    tiling: TilingConfig = field(default_factory=TilingConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PreprocessingConfig":
        with open(path, "r", encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh) or {}
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PreprocessingConfig":
        unknown = set(raw) - {"tissue", "stain", "tiling"}
        if unknown:
            raise ValueError(f"Unknown config section(s): {sorted(unknown)}")
        return cls(
            tissue=build_config(TissueConfig, raw.get("tissue")),
            stain=build_config(StainConfig, raw.get("stain")),
            tiling=build_config(TilingConfig, raw.get("tiling")),
        )

    def to_yaml(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(asdict(self), fh, sort_keys=False)


def build_config(cls, raw: dict[str, Any] | None):
    """Build a config dataclass, rejecting unknown keys loudly.

    A silently ignored typo in a YAML key is exactly the kind of bug that
    makes a run irreproducible, so this raises instead. Shared with
    :mod:`training.config`, which follows the same discipline.
    """
    if not raw:
        return cls()
    valid = {f.name for f in cls.__dataclass_fields__.values()}
    unknown = set(raw) - valid
    if unknown:
        raise ValueError(f"Unknown key(s) for {cls.__name__}: {sorted(unknown)}")
    return cls(**raw)
