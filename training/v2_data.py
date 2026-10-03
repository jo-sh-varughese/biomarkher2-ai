"""Datasets for the multi-task (U-Net + score head) training.

Sites
=====
* ``her2_ihc_40x`` -- our training source. Patch label = the FOLDER class
  (the patch's own intensity class, see PHASE2.md); the slide label (filename
  prefix) is carried too, for reporting. Splits come from the frozen
  ``configs/splits/her2_ihc_40x_split.json`` (fit / val / holdout), the same
  split every earlier run used.
* ``bci`` -- Liu et al. 2022. Label = the HER2 score in the filename (case
  level, from the pathology report). Its ``train`` folder is split once,
  deterministically, into fit / val; its ``test`` folder is test only.

What a sample is
================
One image file, decoded to uint8 on a CPU worker and nothing more. Everything
per-pixel (scale matching, pseudo-labels, augmentation, tiling) happens on the
GPU in training/v2_engine.py. BCI images are scanned at about half our
magnification; ``view`` says how the engine should bring them to 40x:

* ``crop2x`` (BCI training): a random 512 px crop, upsampled 2x to 1024.
* ``quad2x`` (BCI evaluation): all four 512 px quadrants, each upsampled 2x --
  the whole field at matched scale, 16 tiles.
* ``native`` (our data): the 1024 px patch as is, 4 tiles.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from PIL import Image

SCORES = ("0", "1+", "2+", "3+")
FOLDER_TO_SCORE = {"class_0": 0, "class_1+": 1, "class_2+": 2, "class_3+": 3}
SITES = ("her2_ihc_40x", "bci")


@dataclass(frozen=True)
class Sample:
    path: str
    site: str
    label: int
    """Training/evaluation target (0..3)."""
    slide_label: int
    """Case/slide-level score (equals ``label`` for BCI)."""
    has_seg: bool
    """Whether pseudo-label segmentation supervision applies (our site only)."""
    view: str


def _slide_score(name: str) -> int:
    match = re.search(r"her2-(0|1\+|2\+|3\+)-score", name)
    if not match:
        raise ValueError(f"No slide score in {name!r}")
    return SCORES.index(match.group(1))


def bci_score(name: str) -> int:
    match = re.search(r"_(0|1\+|2\+|3\+)\.png$", name)
    if not match:
        raise ValueError(f"No HER2 score in BCI filename {name!r}")
    return SCORES.index(match.group(1))


def her2_ihc_40x_samples(patch_root: str | Path, split_json: str | Path, split: str, limit_per_class: int | None = None, seed: int = 0) -> list[Sample]:
    """Our patches for one split side, located by file name under ``patch_root``."""
    ids = json.loads(Path(split_json).read_text(encoding="utf-8"))["patch_ids"][split]
    wanted = {Path(i).name for i in ids}
    found: dict[str, Path] = {}
    for path in Path(patch_root).glob("*/class_*/*"):
        # Six holdout patches are .jpg; everything else is .png.
        if path.suffix.lower() in (".png", ".jpg", ".jpeg") and path.name in wanted:
            found[path.name] = path
    missing = len(wanted) - len(found)
    if missing:
        raise FileNotFoundError(f"{missing} of {len(wanted)} {split} patches not found under {patch_root}")
    samples = [
        Sample(str(p), "her2_ihc_40x", FOLDER_TO_SCORE[p.parent.name], _slide_score(p.name), True, "native")
        for _, p in sorted(found.items())
    ]
    return _limit(samples, limit_per_class, seed)


def bci_samples(bci_root: str | Path, split: str, val_fraction: float = 0.1, seed: int = 20261002, limit_per_class: int | None = None, names: set[str] | None = None) -> list[Sample]:
    """BCI IHC images. ``split``: "fit" / "val" (from BCI train) or "test"."""
    sub = "test" if split == "test" else "train"
    folder = Path(bci_root) / sub
    if not folder.is_dir() and (Path(bci_root) / f"IHC_{sub}").is_dir():
        folder = Path(bci_root) / f"IHC_{sub}"  # the local sample layout (data/external/bci)
    paths = sorted(folder.glob("*.png"))
    if not paths:
        raise FileNotFoundError(f"No BCI images in {folder}")
    if names is not None:
        paths = [p for p in paths if p.name in names]
    if split in ("fit", "val"):
        rng = random.Random(seed)
        by_label: dict[int, list[Path]] = {}
        for p in paths:
            by_label.setdefault(bci_score(p.name), []).append(p)
        chosen = []
        for label in sorted(by_label):
            group = sorted(by_label[label])
            rng.shuffle(group)
            n_val = max(1, int(round(len(group) * val_fraction)))
            chosen += group[:n_val] if split == "val" else group[n_val:]
        paths = sorted(chosen)
    view = "crop2x" if split == "fit" else "quad2x"
    samples = [Sample(str(p), "bci", bci_score(p.name), bci_score(p.name), False, view) for p in paths]
    return _limit(samples, limit_per_class, seed)


def _limit(samples: list[Sample], per_class: int | None, seed: int) -> list[Sample]:
    if not per_class:
        return samples
    rng = random.Random(seed)
    out = []
    for label in range(len(SCORES)):
        group = [s for s in samples if s.label == label]
        rng.shuffle(group)
        out += group[:per_class]
    return sorted(out, key=lambda s: s.path)


class ImageDataset(torch.utils.data.Dataset):
    """Decodes one file; for ``crop2x`` also takes the random 512 crop (cheap, CPU)."""

    def __init__(self, samples: list[Sample], train: bool) -> None:
        self.samples = samples
        self.train = train

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> dict:
        s = self.samples[index]
        image = Image.open(s.path).convert("RGB")
        if s.view == "crop2x":
            w, h = image.size
            if self.train:
                left, top = random.randint(0, w - 512), random.randint(0, h - 512)
            else:
                left, top = (w - 512) // 2, (h - 512) // 2
            image = image.crop((left, top, left + 512, top + 512))
        array = torch.from_numpy(np.array(image, dtype=np.uint8)).permute(2, 0, 1).contiguous()
        return {"image": array, "label": s.label, "slide_label": s.slide_label, "has_seg": s.has_seg,
                "view": s.view, "site": s.site, "path": s.path}


def collate(batch: list[dict]) -> dict:
    """Images stay a list: crop2x samples are 512 px, the rest 1024 px."""
    return {
        "images": [b["image"] for b in batch],
        "label": torch.tensor([b["label"] for b in batch]),
        "slide_label": torch.tensor([b["slide_label"] for b in batch]),
        "has_seg": torch.tensor([b["has_seg"] for b in batch]),
        "view": [b["view"] for b in batch],
        "site": [b["site"] for b in batch],
        "path": [b["path"] for b in batch],
    }


def balanced_sampler(samples: list[Sample], num_samples: int, seed: int) -> torch.utils.data.WeightedRandomSampler:
    """Every (site, label) group drawn equally often, with replacement."""
    groups: dict[tuple, int] = {}
    for s in samples:
        groups[(s.site, s.label)] = groups.get((s.site, s.label), 0) + 1
    weights = torch.tensor([1.0 / groups[(s.site, s.label)] for s in samples], dtype=torch.double)
    generator = torch.Generator().manual_seed(seed)
    return torch.utils.data.WeightedRandomSampler(weights, num_samples=num_samples, replacement=True, generator=generator)
