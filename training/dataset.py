"""Torch dataset over the cached pseudo-label targets.

Augmentation here is restricted to the eight dihedral transforms -- horizontal
and vertical flips and 90-degree rotations. That restriction is not
conservatism, it is a consequence of what the labels are.

The intensity classes are defined by DAB optical density thresholds. Colour
jitter, brightness jitter, contrast changes and stain augmentation all move
optical density, which means they move a pixel across a class boundary while
leaving its cached label where it was. The augmented pair would then be
mislabelled by construction, and the model would be trained to ignore exactly
the signal it is supposed to measure. Geometric transforms move pixels without
touching their colour, so image and label stay consistent.

Rotation by arbitrary angles and scaling are excluded for the same reason one
step removed: both interpolate, and interpolating a label map invents classes
that were never assigned.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

from preprocessing.baseline import NUM_CLASSES
from preprocessing.stains import dab_channel
from training.pseudo_labels import PseudoLabelCache


@dataclass
class Sample:
    """One training example, before collation."""

    pixel_values: torch.Tensor  # 3xHxW float, un-normalised 0..1
    labels: torch.Tensor  # HxW long
    patch_id: str


class PseudoLabelDataset(Dataset):
    """Serves cached (image, label) pairs, optionally augmented."""

    def __init__(
        self,
        cache: PseudoLabelCache,
        patch_ids: list[str],
        augment: bool = False,
        seed: int = 0,
        folder_classes: dict[str, int] | None = None,
        include_dab: bool = False,
    ) -> None:
        if not patch_ids:
            raise ValueError("Refusing to build a dataset over zero patches.")
        self.cache = cache
        self.patch_ids = list(patch_ids)
        self.augment = augment
        self.folder_classes = folder_classes or {}
        self.include_dab = include_dab
        """When True, a 4th channel (DAB optical density) is appended to
        ``pixel_values`` -- see models/unet_seg.py's module docstring for
        why. Computed AFTER augmentation, from the already-transformed RGB,
        so it is consistent with the geometric transform by construction
        rather than needing its own copy of the flip/rotation logic."""
        self._rng = np.random.default_rng(seed)

    def __len__(self) -> int:
        return len(self.patch_ids)

    def __getitem__(self, index: int) -> dict:
        patch_id = self.patch_ids[index]
        rgb, label = self.cache.read(patch_id)
        if self.augment:
            rgb, label = self._augment(rgb, label)

        pixels = torch.from_numpy(np.ascontiguousarray(rgb)).permute(2, 0, 1).float() / 255.0
        if self.include_dab:
            dab = dab_channel(rgb).astype(np.float32)
            dab_tensor = torch.from_numpy(np.ascontiguousarray(dab)).unsqueeze(0)
            pixels = torch.cat([pixels, dab_tensor], dim=0)
        return {
            "pixel_values": pixels,
            "labels": torch.from_numpy(np.ascontiguousarray(label)).long(),
            "patch_id": patch_id,
            "folder_class": self.folder_classes.get(patch_id, -1),
        }

    def _augment(self, rgb: np.ndarray, label: np.ndarray):
        """Apply the same dihedral transform to image and label."""
        k = int(self._rng.integers(0, 4))
        if k:
            rgb = np.rot90(rgb, k, axes=(0, 1))
            label = np.rot90(label, k, axes=(0, 1))
        if self._rng.random() < 0.5:
            rgb = rgb[:, ::-1]
            label = label[:, ::-1]
        if self._rng.random() < 0.5:
            rgb = rgb[::-1]
            label = label[::-1]
        return rgb, label


def _strided(patch_ids: list[str], limit: int | None) -> list[str]:
    """At most ``limit`` ids, spread evenly over the whole list."""
    if limit is None or limit >= len(patch_ids):
        return list(patch_ids)
    if limit <= 0:
        return []
    step = len(patch_ids) / limit
    return [patch_ids[int(i * step)] for i in range(limit)]


def class_pixel_counts(
    cache: PseudoLabelCache, patch_ids: list[str], limit: int | None = None
) -> dict[int, int]:
    """Count label pixels per class, for reporting and optional CE weights.

    ``limit`` takes an evenly-spaced stride through the list, never a prefix.
    Patch ids sort by class folder, so a prefix would sample one class and
    report a balance that is wrong in exactly the direction that matters: the
    first Phase 2 40x run printed weak (1+) at 4.9% of pixels when the true
    figure over its training tiles was 7.0%.
    """
    counts = {c: 0 for c in range(NUM_CLASSES)}
    for patch_id in _strided(patch_ids, limit):
        _, label = cache.read(patch_id)
        values, found = np.unique(label, return_counts=True)
        for value, count in zip(values.tolist(), found.tolist()):
            counts[int(value)] = counts.get(int(value), 0) + int(count)
    return counts


def build_loader(
    dataset: PseudoLabelDataset,
    batch_size: int,
    shuffle: bool,
    num_workers: int = 0,
    seed: int = 0,
) -> DataLoader:
    generator = torch.Generator()
    generator.manual_seed(seed)
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        generator=generator if shuffle else None,
        drop_last=False,
        pin_memory=False,
    )
