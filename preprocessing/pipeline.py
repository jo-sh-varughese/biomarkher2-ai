"""The composed preprocessing pipeline -- the public entry point for Phase 1.

One call turns raw RGB pixels into everything downstream needs: a tissue
mask, deconvolved stain channels, a classical intensity map, area
percentages, and tiles. Stages are also individually importable so they can
be tested and inspected on their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .baseline import (
    AreaDistribution,
    area_distribution,
    dab_statistics,
    intensity_map,
)
from .config import PreprocessingConfig
from .stains import DAB_CHANNEL, H_CHANNEL, apply_normalization, deconvolve
from .tiling import Tile, extract_tiles
from .tissue import detect_tissue, tissue_fraction


@dataclass
class PreprocessedPatch:
    """Everything Phase 1 derives from a single input image."""

    patch_id: str
    original: np.ndarray
    normalized: np.ndarray
    tissue_mask: np.ndarray
    hematoxylin: np.ndarray
    dab: np.ndarray
    intensity: np.ndarray
    areas: AreaDistribution
    dab_stats: dict[str, float]
    tiles: list[Tile] = field(default_factory=list)

    @property
    def tissue_fraction(self) -> float:
        return tissue_fraction(self.tissue_mask)


class PreprocessingPipeline:
    """Composes tissue detection, normalization, deconvolution and tiling."""

    def __init__(self, config: PreprocessingConfig | None = None) -> None:
        self.config = config or PreprocessingConfig()

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PreprocessingPipeline":
        return cls(PreprocessingConfig.from_yaml(path))

    def run(
        self,
        rgb: np.ndarray,
        patch_id: str = "<unnamed>",
        with_tiles: bool = False,
    ) -> PreprocessedPatch:
        """Run every Phase 1 stage on one image.

        Ordering matters and is deliberate: tissue is detected on the
        original pixels, then normalization is applied using that mask (so
        the statistics come from tissue rather than glass), then the tissue
        mask is recomputed on the normalized image if normalization actually
        changed anything.
        """
        original = np.asarray(rgb, dtype=np.uint8)
        if original.ndim != 3 or original.shape[-1] != 3:
            raise ValueError(f"Expected an HxWx3 RGB image, got shape {original.shape}")

        mask = detect_tissue(original, self.config.tissue)

        normalized = apply_normalization(original, self.config.stain, tissue_mask=mask)
        if self.config.stain.normalization.lower() != "none":
            mask = detect_tissue(normalized, self.config.tissue)

        stains = deconvolve(
            normalized, background_intensity=self.config.stain.background_intensity
        )
        classes = intensity_map(normalized, mask, self.config.stain)

        tiles: list[Tile] = []
        if with_tiles:
            tiles = extract_tiles(normalized, mask, self.config.tiling)

        return PreprocessedPatch(
            patch_id=patch_id,
            original=original,
            normalized=normalized,
            tissue_mask=mask,
            hematoxylin=stains[..., H_CHANNEL],
            dab=stains[..., DAB_CHANNEL],
            intensity=classes,
            areas=area_distribution(classes),
            dab_stats=dab_statistics(normalized, mask, self.config.stain),
            tiles=tiles,
        )

    def run_source(
        self,
        source,
        patch_ids: list[str] | None = None,
        with_tiles: bool = False,
    ):
        """Run the pipeline over a :class:`~preprocessing.sources.PatchSource`."""
        ids = patch_ids if patch_ids is not None else source.list_ids()
        for patch_id in ids:
            yield self.run(
                source.read_patch(patch_id), patch_id=patch_id, with_tiles=with_tiles
            )
