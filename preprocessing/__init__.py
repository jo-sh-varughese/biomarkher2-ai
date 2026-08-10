"""BioMarkHER2 preprocessing package (Phase 1)."""

from .baseline import (
    CLASS_BACKGROUND,
    CLASS_MODERATE,
    CLASS_NAMES,
    CLASS_NEGATIVE,
    CLASS_STRONG,
    CLASS_WEAK,
    NUM_CLASSES,
    TISSUE_CLASSES,
    AreaDistribution,
    area_distribution,
    dab_statistics,
    intensity_map,
)
from .config import (
    PreprocessingConfig,
    StainConfig,
    TilingConfig,
    TissueConfig,
)
from .pipeline import PreprocessedPatch, PreprocessingPipeline
from .sources import DirectoryPatchSource, PatchRecord, PatchSource
from .stains import (
    DAB,
    HEMATOXYLIN,
    build_stain_matrix,
    dab_channel,
    deconvolve,
    hematoxylin_channel,
    od_to_rgb,
    rgb_to_od,
)
from .tiling import Tile, extract_tiles, tile_positions
from .tissue import detect_tissue, tissue_fraction

__all__ = [
    "AreaDistribution",
    "CLASS_BACKGROUND",
    "CLASS_MODERATE",
    "CLASS_NAMES",
    "CLASS_NEGATIVE",
    "CLASS_STRONG",
    "CLASS_WEAK",
    "DAB",
    "DirectoryPatchSource",
    "HEMATOXYLIN",
    "NUM_CLASSES",
    "PatchRecord",
    "PatchSource",
    "PreprocessedPatch",
    "PreprocessingConfig",
    "PreprocessingPipeline",
    "StainConfig",
    "TISSUE_CLASSES",
    "Tile",
    "TilingConfig",
    "TissueConfig",
    "area_distribution",
    "build_stain_matrix",
    "dab_channel",
    "dab_statistics",
    "deconvolve",
    "detect_tissue",
    "extract_tiles",
    "hematoxylin_channel",
    "intensity_map",
    "od_to_rgb",
    "rgb_to_od",
    "tile_positions",
    "tissue_fraction",
]
