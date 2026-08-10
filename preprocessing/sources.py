"""Data sources behind a single interface.

Everything downstream talks to :class:`PatchSource` and never to a file
format. Today the only real implementation reads the HER2_IHC_40X patch
directories; when whole-slide images eventually arrive, an OpenSlide-backed
implementation drops in behind the same interface without restructuring the
pipeline.

Two properties of the HER2_IHC_40X dataset are encoded here deliberately:

* The folder name is the patch-level intensity label, while the filename
  prefix records the source slide's *overall* score. These genuinely differ
  (a slide scored 0 overall still contains some faintly-stained patches), so
  both are exposed rather than one being quietly discarded.

* There are no per-slide identifiers. Provenance collapses to eight groups
  (``her2-{0,1+,2+,3+}-score_{train,test}``). :meth:`group_key` therefore
  returns a provenance group, NOT a slide. Any split built on it is grouped
  more coarsely than true slide-level grouping, and reporting must say so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol, runtime_checkable

import numpy as np
from PIL import Image

# Folder name -> patch-level intensity class, in the 5-class scheme where
# 0 is background. There is no folder for background: these are all tissue
# patches, and background is identified per-pixel by the tissue mask.
FOLDER_TO_CLASS: dict[str, int] = {
    "class_0": 1,    # negative
    "class_1+": 2,   # weak
    "class_2+": 3,   # moderate
    "class_3+": 4,   # strong
}

# The HER2 score a folder corresponds to, for reporting in human terms.
FOLDER_TO_SCORE: dict[str, str] = {
    "class_0": "0",
    "class_1+": "1+",
    "class_2+": "2+",
    "class_3+": "3+",
}

_FILENAME_RE = re.compile(r"^her2-(0|1\+|2\+|3\+)-score_(train|test)_")

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


@dataclass(frozen=True)
class PatchRecord:
    """Metadata for one patch, without the pixels."""

    patch_id: str
    path: Path
    patch_class: int
    """Patch-level intensity class (1..4), from the containing folder."""

    patch_score: str
    """The same, as a human-readable HER2 score string."""

    slide_score: str | None
    """Overall HER2 score of the source slide, parsed from the filename."""

    provenance: str
    """Coarse provenance group -- see the module docstring. Used for grouping."""

    split: str
    """Which top-level split directory the patch came from."""


@runtime_checkable
class PatchSource(Protocol):
    """The single interface every downstream stage depends on."""

    def list_ids(self) -> list[str]:
        ...

    def read_patch(self, patch_id: str) -> np.ndarray:
        """Return HxWx3 uint8 RGB pixels."""
        ...

    def group_key(self, patch_id: str) -> str:
        """Grouping key for leakage-free splitting."""
        ...

    def label(self, patch_id: str) -> int | None:
        """Patch-level intensity class, or None when unlabelled."""
        ...


class DirectoryPatchSource:
    """Reads class-labelled patch folders from disk.

    Expects ``root/<split>/<class folder>/<image files>``, or
    ``root/<class folder>/<image files>`` when ``splits`` is None.
    """

    def __init__(
        self,
        root: str | Path,
        splits: list[str] | None = None,
        folder_to_class: dict[str, int] | None = None,
    ) -> None:
        self.root = Path(root)
        if not self.root.is_dir():
            raise FileNotFoundError(f"Patch root does not exist: {self.root}")
        self.folder_to_class = folder_to_class or FOLDER_TO_CLASS
        self._records: dict[str, PatchRecord] = {}
        self._scan(splits)
        if not self._records:
            raise ValueError(
                f"No patches found under {self.root}. Expected class folders "
                f"named {sorted(self.folder_to_class)}."
            )

    def _scan(self, splits: list[str] | None) -> None:
        if splits is None:
            split_dirs = [(self.root, "")]
        else:
            split_dirs = [(self.root / s, s) for s in splits]

        for split_dir, split_name in split_dirs:
            if not split_dir.is_dir():
                raise FileNotFoundError(f"Split directory not found: {split_dir}")
            for folder, cls in self.folder_to_class.items():
                class_dir = split_dir / folder
                if not class_dir.is_dir():
                    continue
                for path in sorted(class_dir.iterdir()):
                    if path.suffix.lower() not in IMAGE_SUFFIXES:
                        continue
                    slide_score, origin = _parse_filename(path.name)
                    # Patch ids are unique across the dataset, but prefix with
                    # the split anyway so two sources can be merged safely.
                    patch_id = f"{split_name}/{folder}/{path.name}" if split_name \
                        else f"{folder}/{path.name}"
                    provenance = (
                        f"her2-{slide_score}-score_{origin}"
                        if slide_score and origin
                        else f"{split_name or 'root'}:{folder}"
                    )
                    self._records[patch_id] = PatchRecord(
                        patch_id=patch_id,
                        path=path,
                        patch_class=cls,
                        patch_score=FOLDER_TO_SCORE.get(folder, folder),
                        slide_score=slide_score,
                        provenance=provenance,
                        split=split_name or "root",
                    )

    def list_ids(self) -> list[str]:
        return sorted(self._records)

    def records(self) -> Iterator[PatchRecord]:
        for patch_id in self.list_ids():
            yield self._records[patch_id]

    def record(self, patch_id: str) -> PatchRecord:
        try:
            return self._records[patch_id]
        except KeyError:
            raise KeyError(f"Unknown patch id: {patch_id!r}") from None

    def read_patch(self, patch_id: str) -> np.ndarray:
        path = self.record(patch_id).path
        with Image.open(path) as img:
            return np.asarray(img.convert("RGB"), dtype=np.uint8)

    def group_key(self, patch_id: str) -> str:
        return self.record(patch_id).provenance

    def label(self, patch_id: str) -> int | None:
        return self.record(patch_id).patch_class

    def __len__(self) -> int:
        return len(self._records)


def _parse_filename(name: str) -> tuple[str | None, str | None]:
    """Extract (slide score, origin split) from a HER2_IHC_40X filename.

    Returns (None, None) for names that do not follow the convention, rather
    than guessing -- an unparsed name should be visible, not invented.
    """
    match = _FILENAME_RE.match(name)
    if not match:
        return None, None
    return match.group(1), match.group(2)
