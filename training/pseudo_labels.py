"""Precomputed pixel-level training targets, and what they actually are.

WHAT THESE LABELS ARE
=====================

There are **no pathologist pixel annotations** for this project. Not for
HER2_IHC_40X, and not yet from Kottayam. The dataset provides one HER2 score
per *patch* (the containing folder) and one per *source slide* (the filename
prefix) -- nothing per pixel.

So the dense targets Phase 2 trains on are **pseudo-labels**: the output of
:func:`preprocessing.baseline.intensity_map`, which thresholds DAB optical
density at fixed cut points. They are a clearly-labelled substitute for
annotations that do not exist, written to disk as images precisely so that
they can be looked at and disputed rather than assumed.

Two consequences, both of which must survive into Phase 4:

1. **Circularity.** A model trained on these targets that then agrees with
   these targets has demonstrated nothing. The only meaningful comparison is
   against the pathologist-facing labels the dataset does carry (the folder
   score), with the classical thresholder itself carried through as a control.
   If SegFormer does not beat the thresholder, the honest finding is that it
   adds nothing.

2. **A ceiling.** The thresholder cannot be exceeded on its own terms. What a
   learned model can add is spatial coherence -- thresholding is per-pixel and
   noisy; segmentation sees neighbourhoods -- and robustness to the illumination
   and stain variation that shifts a fixed OD cut point. Those are the things
   worth measuring, not raw agreement.

WHAT THE CACHE STORES
=====================

Per patch, two PNGs and a manifest row:

* ``<stem>_img.png`` -- the RGB the model is fed, downsampled from 1024 to 512.
* ``<stem>_lbl.png`` -- the class index per pixel, 0..4, single-channel.

The pipeline is run at the **full 1024 resolution it was validated at** in
Phase 1, and *then* both image and label are reduced by the same strided
:func:`~preprocessing.tiling.downsample`. Because striding picks pixel
``(2i, 2j)`` from each, label pixel ``(i, j)`` is exactly the class assigned to
image pixel ``(i, j)`` -- no interpolation, no resampling a label map, no
invented intermediate classes. Deriving the label from a downsampled image
instead would change the optical densities the thresholds act on.

Caching rather than recomputing per epoch is not only speed: it fixes the
targets. Morphological cleanup re-run every epoch would be identical anyway,
but a target set on disk is one that can be audited, diffed, and pointed at.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

import numpy as np
from PIL import Image

from preprocessing.baseline import CLASS_NAMES, NUM_CLASSES, TISSUE_CLASSES
from preprocessing.pipeline import PreprocessingPipeline
from preprocessing.tiling import extract_tiles

IMAGE_SUFFIX = "_img.png"
LABEL_SUFFIX = "_lbl.png"
MANIFEST_NAME = "manifest.csv"
SUMMARY_NAME = "summary.json"
TILE_INDEX_NAME = "tiles.json"

_TILE_RE = re.compile(r"__r(\d+)c(\d+)$")


@dataclass
class PseudoLabelRecord:
    """One cached target, plus the numbers needed to audit it."""

    patch_id: str
    """Id of this tile. Equals ``parent_patch_id`` when a source patch yields
    exactly one tile."""

    parent_patch_id: str = ""
    """The source patch this tile was cut from.

    Tiles from one source patch are near-duplicates of each other, so this is
    the grouping key that keeps them off opposite sides of the fit/validation
    boundary. Slide-level grouping is impossible on this dataset; patch-level
    grouping is not, and it is enforced."""

    row: int = 0
    col: int = 0
    source_y: int = 0
    source_x: int = 0
    """Position in the source patch's own pixel frame. Phase 3 stitches
    predictions back using these, so they are recorded now rather than
    recomputed later from assumptions about the grid."""

    image_path: str = ""
    label_path: str = ""
    folder_class: int = 0
    """The patch-level class from the dataset's own folder (1..4). NOT used as
    a training target -- recorded so folder label and pixel pseudo-label can be
    compared."""

    height: int = 0
    width: int = 0
    tissue_fraction: float = 0.0
    dominant_tissue_class: int = 0
    """The most common non-background class in the pseudo-label. Where this
    disagrees with ``folder_class`` the thresholds and the dataset's own
    labelling disagree, and that disagreement is worth seeing."""

    class_fractions: dict[int, float] = field(default_factory=dict)
    """Class index -> fraction of *tissue* area."""

    dab_mean: float | None = None
    dab_p90: float | None = None
    """None when the patch was already cached and so the full-resolution run
    was skipped. Left empty in the manifest rather than filled with a zero,
    which would read as "no staining" instead of "not measured"."""

    def as_row(self) -> dict[str, object]:
        flat: dict[str, object] = {
            "patch_id": self.patch_id,
            "parent_patch_id": self.parent_patch_id,
            "tile_row": self.row,
            "tile_col": self.col,
            "source_y": self.source_y,
            "source_x": self.source_x,
            "image_path": self.image_path,
            "label_path": self.label_path,
            "folder_class": self.folder_class,
            "dominant_tissue_class": self.dominant_tissue_class,
            "agrees_with_folder": int(self.dominant_tissue_class == self.folder_class),
            "height": self.height,
            "width": self.width,
            "tissue_fraction": round(self.tissue_fraction, 6),
            "dab_mean": "" if self.dab_mean is None else round(self.dab_mean, 6),
            "dab_p90": "" if self.dab_p90 is None else round(self.dab_p90, 6),
        }
        for cls in TISSUE_CLASSES:
            name = CLASS_NAMES[cls].split(" ")[0]
            flat[f"frac_{name}"] = round(self.class_fractions.get(cls, 0.0), 6)
        return flat


class PseudoLabelCache:
    """Reads and writes the on-disk target cache."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    # -- tile ids ------------------------------------------------------

    @staticmethod
    def tile_id(parent_patch_id: str, row: int, col: int) -> str:
        """Id for one tile of a source patch.

        Encoded in the filename rather than held in a side table so that a
        cached file names its own provenance: anyone looking at the cache
        directory can see which patch a tile came from and where in it.
        """
        path = Path(parent_patch_id)
        return str(path.with_name(f"{path.stem}__r{row}c{col}{path.suffix}")).replace(
            "\\", "/"
        )

    @staticmethod
    def parse_tile_id(tile_id: str) -> tuple[int, int]:
        match = _TILE_RE.search(Path(tile_id).stem)
        if not match:
            raise ValueError(f"Not a tile id: {tile_id!r}")
        return int(match.group(1)), int(match.group(2))

    @staticmethod
    def parent_of(tile_id: str) -> str:
        """The source patch id a tile came from."""
        path = Path(tile_id)
        stem = _TILE_RE.sub("", path.stem)
        return str(path.with_name(f"{stem}{path.suffix}")).replace("\\", "/")

    def tile_ids(self, parent_patch_id: str) -> list[str]:
        """Tile ids already cached for a source patch, in grid order."""
        path = Path(parent_patch_id)
        directory = self.root / path.parent
        if not directory.is_dir():
            return []
        found = []
        for image_path in directory.glob(f"{path.stem}__r*c*{IMAGE_SUFFIX}"):
            stem = image_path.name[: -len(IMAGE_SUFFIX)]
            tile = str((path.parent / f"{stem}{path.suffix}")).replace("\\", "/")
            found.append((self.parse_tile_id(tile), tile))
        return [tile for _, tile in sorted(found)]

    # -- paths ---------------------------------------------------------

    def paths(self, patch_id: str) -> tuple[Path, Path]:
        """Cache paths for a patch id, mirroring the source directory layout."""
        relative = Path(_safe_relative(patch_id))
        base = self.root / relative.parent / relative.stem
        return (
            base.with_name(base.name + IMAGE_SUFFIX),
            base.with_name(base.name + LABEL_SUFFIX),
        )

    def exists(self, patch_id: str) -> bool:
        image_path, label_path = self.paths(patch_id)
        return image_path.is_file() and label_path.is_file()

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_NAME

    @property
    def summary_path(self) -> Path:
        return self.root / SUMMARY_NAME

    # -- io ------------------------------------------------------------

    def read(self, patch_id: str) -> tuple[np.ndarray, np.ndarray]:
        """Return (rgb uint8 HxWx3, label uint8 HxW) for a cached patch."""
        image_path, label_path = self.paths(patch_id)
        if not image_path.is_file() or not label_path.is_file():
            raise FileNotFoundError(
                f"Patch {patch_id!r} is not in the cache at {self.root}. "
                "Run scripts/build_pseudo_labels.py first."
            )
        # np.array rather than np.asarray: PIL hands back a read-only buffer,
        # and augmentation needs to be free to write into these.
        with Image.open(image_path) as img:
            rgb = np.array(img.convert("RGB"), dtype=np.uint8)
        with Image.open(label_path) as img:
            label = np.array(img.convert("L"), dtype=np.uint8)
        if label.shape != rgb.shape[:2]:
            raise ValueError(
                f"Cached image and label disagree in shape for {patch_id!r}: "
                f"{rgb.shape[:2]} vs {label.shape}"
            )
        return rgb, label

    def write(self, patch_id: str, rgb: np.ndarray, label: np.ndarray) -> tuple[Path, Path]:
        image_path, label_path = self.paths(patch_id)
        image_path.parent.mkdir(parents=True, exist_ok=True)
        if label.max(initial=0) >= NUM_CLASSES:
            raise ValueError(
                f"Label for {patch_id!r} contains class {int(label.max())}, but "
                f"only 0..{NUM_CLASSES - 1} are defined."
            )
        Image.fromarray(np.asarray(rgb, dtype=np.uint8), mode="RGB").save(image_path)
        # Mode "L", storing the class index directly. Deliberately not a
        # palette image: the raw stored value must be the class the loss sees,
        # so an accidental palette remap cannot silently relabel the data.
        Image.fromarray(np.asarray(label, dtype=np.uint8), mode="L").save(label_path)
        return image_path, label_path

    # -- manifest ------------------------------------------------------

    @property
    def tile_index_path(self) -> Path:
        return self.root / TILE_INDEX_NAME

    def write_manifest(self, records: Sequence[PseudoLabelRecord]) -> None:
        if not records:
            raise ValueError("Refusing to write an empty pseudo-label manifest.")
        self.root.mkdir(parents=True, exist_ok=True)
        rows = [record.as_row() for record in records]
        with open(self.manifest_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        with open(self.summary_path, "w", encoding="utf-8") as fh:
            json.dump(summarize(records), fh, indent=2)

        # Persisted so a training run can expand a patch-level split into
        # tiles without re-deriving the grid, and so the expansion it used is
        # itself an artifact rather than a computation nobody can check.
        index: dict[str, list[str]] = {}
        for record in records:
            index.setdefault(record.parent_patch_id, []).append(record.patch_id)
        with open(self.tile_index_path, "w", encoding="utf-8") as fh:
            json.dump(index, fh, indent=2)

    def load_tile_index(self) -> dict[str, list[str]]:
        if not self.tile_index_path.is_file():
            raise FileNotFoundError(
                f"No tile index at {self.tile_index_path}. "
                "Run scripts/build_pseudo_labels.py first."
            )
        with open(self.tile_index_path, encoding="utf-8") as fh:
            return json.load(fh)

    def load_manifest(self) -> list[dict[str, str]]:
        if not self.manifest_path.is_file():
            raise FileNotFoundError(f"No manifest at {self.manifest_path}")
        with open(self.manifest_path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))


def build_record(
    patch_id: str,
    folder_class: int,
    result,
    image_path: Path,
    label_path: Path,
    label: np.ndarray,
    parent_patch_id: str | None = None,
    row: int = 0,
    col: int = 0,
    source_y: int = 0,
    source_x: int = 0,
) -> PseudoLabelRecord:
    """Assemble the audit row for one cached tile."""
    tissue = np.isin(label, TISSUE_CLASSES)
    tissue_pixels = int(tissue.sum())
    fractions = {
        cls: (float((label == cls).sum()) / tissue_pixels if tissue_pixels else 0.0)
        for cls in TISSUE_CLASSES
    }
    dominant = max(TISSUE_CLASSES, key=lambda c: fractions[c]) if tissue_pixels else 0
    return PseudoLabelRecord(
        patch_id=patch_id,
        parent_patch_id=parent_patch_id or patch_id,
        row=row,
        col=col,
        source_y=source_y,
        source_x=source_x,
        image_path=str(image_path),
        label_path=str(label_path),
        folder_class=folder_class,
        height=int(label.shape[0]),
        width=int(label.shape[1]),
        tissue_fraction=tissue_pixels / float(label.size),
        dominant_tissue_class=int(dominant),
        class_fractions=fractions,
        dab_mean=_maybe(result.dab_stats.get("dab_mean")),
        dab_p90=_maybe(result.dab_stats.get("dab_p90")),
    )


def _maybe(value) -> float | None:
    return None if value is None else float(value)


def build_cache(
    source,
    pipeline: PreprocessingPipeline,
    cache: PseudoLabelCache,
    patch_ids: Iterable[str] | None = None,
    overwrite: bool = False,
    progress: Callable[[int, int, str], None] | None = None,
) -> list[PseudoLabelRecord]:
    """Generate pseudo-labels for every requested patch and cache them.

    The pipeline is run at the source resolution, then image and label are cut
    into tiles together by :func:`~preprocessing.tiling.extract_tiles`. Tiling
    subsumes the plain downsample that used to be here: on a 1024 patch,
    ``downsample=2, patch_size=512`` yields exactly one 512 tile at effective
    20x (the old behaviour), while ``downsample=1`` yields four 512 tiles at
    native 40x. One code path, and the magnification is a config choice rather
    than a property of the code.

    Tiles are recorded with their position in the source patch, and with the
    patch they came from, so that (a) Phase 3 can stitch them back and (b)
    tiles of one patch never straddle the fit/validation boundary.
    """
    ids = list(patch_ids) if patch_ids is not None else source.list_ids()
    tiling = pipeline.config.tiling
    records: list[PseudoLabelRecord] = []
    empty: list[str] = []

    for index, patch_id in enumerate(ids, start=1):
        if progress is not None:
            progress(index, len(ids), patch_id)

        folder_class = int(source.label(patch_id) or 0)
        tile_ids = cache.tile_ids(patch_id)

        if not overwrite and tile_ids and all(cache.exists(t) for t in tile_ids):
            for tile_id in tile_ids:
                _, label = cache.read(tile_id)
                image_path, label_path = cache.paths(tile_id)
                row, col = cache.parse_tile_id(tile_id)
                records.append(
                    build_record(
                        patch_id=tile_id,
                        parent_patch_id=patch_id,
                        row=row,
                        col=col,
                        source_y=row * tiling.patch_size * tiling.downsample,
                        source_x=col * tiling.patch_size * tiling.downsample,
                        folder_class=folder_class,
                        result=_CachedStats(),
                        image_path=str(image_path),
                        label_path=str(label_path),
                        label=label,
                    )
                )
            continue

        result = pipeline.run(source.read_patch(patch_id), patch_id=patch_id)
        # The label is tiled by the same call, in the same frame, so a tile's
        # label pixel and its image pixel are the same pixel by construction.
        image_tiles = extract_tiles(result.normalized, result.tissue_mask, tiling)
        # extract_tiles wants HxWx3, so the single-channel label rides through
        # as a grey image and is unpacked below. Same config and same mask, so
        # the two calls select the same tiles in the same order -- asserted
        # rather than assumed, because a silent misalignment here would cap
        # accuracy forever without ever looking like a bug.
        label_full = np.stack([result.intensity] * 3, axis=-1)
        label_tiles = extract_tiles(label_full, result.tissue_mask, tiling)
        assert [(t.row, t.col) for t in image_tiles] == [
            (t.row, t.col) for t in label_tiles
        ], "image and label tiling disagree"

        if not image_tiles:
            # Every tile fell below min_tissue_fraction. Recorded, not skipped
            # silently -- a patch vanishing from training should be visible.
            empty.append(patch_id)
            continue

        for image_tile, label_tile in zip(image_tiles, label_tiles):
            tile_id = cache.tile_id(patch_id, image_tile.row, image_tile.col)
            label = label_tile.image[..., 0]
            image_path, label_path = cache.write(tile_id, image_tile.image, label)
            records.append(
                build_record(
                    patch_id=tile_id,
                    parent_patch_id=patch_id,
                    row=image_tile.row,
                    col=image_tile.col,
                    source_y=image_tile.source_y,
                    source_x=image_tile.source_x,
                    folder_class=folder_class,
                    result=result,
                    image_path=str(image_path),
                    label_path=str(label_path),
                    label=label,
                )
            )

    if empty:
        print(
            f"NOTE: {len(empty)} patch(es) produced no tile above "
            f"min_tissue_fraction={tiling.min_tissue_fraction} and are absent "
            f"from the cache, e.g. {empty[:3]}"
        )
    return records


class _CachedStats:
    """Stand-in for a pipeline result when a patch was already cached.

    The DAB statistics come from the full-resolution run and are not
    recoverable from the cached files alone; they are reported as 0 rather
    than recomputed at the wrong resolution, which would put two different
    quantities in the same manifest column.
    """

    dab_stats: dict[str, float] = {}


def stained_fraction(record: PseudoLabelRecord) -> float:
    """Fraction of tissue area at 1+ or above."""
    return sum(
        record.class_fractions.get(cls, 0.0) for cls in TISSUE_CLASSES if cls > 1
    )


def summarize(records: Sequence[PseudoLabelRecord]) -> dict:
    """Aggregate the manifest into the numbers worth reading first.

    The headline check is **monotonicity of stained area across the folder
    classes**, not per-patch agreement between the pseudo-label and the folder
    label. Agreement is the wrong question and answering it is misleading: on
    a 1+ or 2+ patch most tissue pixels are unstained cytoplasm and stroma, so
    the most common pseudo-label class is "negative" no matter how correct the
    thresholds are. Comparing that to a folder label of "1+" scores 0% and
    means nothing.

    What the folder labels can actually test is ordering. If the deconvolution
    and the thresholds are sound, the fraction of tissue stained at 1+ or
    above must rise across folder classes 0 -> 1+ -> 2+ -> 3+. If it does not,
    something upstream is wrong and every downstream number inherits it.
    """
    by_folder: dict[int, list[PseudoLabelRecord]] = {}
    for record in records:
        by_folder.setdefault(record.folder_class, []).append(record)

    per_class = {}
    means: list[tuple[int, float]] = []
    for folder_class, group in sorted(by_folder.items()):
        mean_stained = float(np.mean([stained_fraction(r) for r in group]))
        means.append((folder_class, mean_stained))
        per_class[CLASS_NAMES.get(folder_class, str(folder_class))] = {
            "patches": len(group),
            "mean_tissue_fraction": round(
                float(np.mean([r.tissue_fraction for r in group])), 4
            ),
            "mean_stained_fraction": round(mean_stained, 4),
            "median_stained_fraction": round(
                float(np.median([stained_fraction(r) for r in group])), 4
            ),
            "mean_class_fractions": {
                CLASS_NAMES[cls]: round(
                    float(np.mean([r.class_fractions.get(cls, 0.0) for r in group])), 4
                )
                for cls in TISSUE_CLASSES
            },
            # Retained as a description of the targets, not as a score.
            "most_common_pseudo_class": _mode(
                [r.dominant_tissue_class for r in group]
            ),
        }

    values = [m for _, m in means]
    monotonic = all(a < b for a, b in zip(values, values[1:]))
    return {
        "what_these_are": (
            "Pseudo-labels from fixed DAB optical-density thresholds, NOT "
            "pathologist annotations. See training/pseudo_labels.py."
        ),
        "patches": len(records),
        "sanity_check": (
            "Mean stained tissue fraction must increase across folder classes "
            "0 -> 1+ -> 2+ -> 3+."
        ),
        "stained_fraction_is_monotonic": monotonic,
        "mean_stained_fraction_by_folder_class": {
            CLASS_NAMES.get(c, str(c)): round(v, 4) for c, v in means
        },
        "per_folder_class": per_class,
    }


def _mode(values: Sequence[int]) -> int:
    counts: dict[int, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return max(counts, key=lambda k: counts[k])


def _safe_relative(patch_id: str) -> str:
    """Reject patch ids that would escape the cache root."""
    parts = Path(patch_id).parts
    if Path(patch_id).is_absolute() or ".." in parts:
        raise ValueError(f"Unsafe patch id for a cache path: {patch_id!r}")
    return patch_id
