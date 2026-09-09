"""Cross-group stain variation, from adaptive per-patch stain-vector estimates.

This is the aggregation Objective 1 (adaptive stain-vector analysis) was
missing: preprocessing/stains.py already estimates a stain matrix per patch
(Macenko et al., 2009), but nothing before this module asked how much that
estimate actually *varies* across the dataset, or reported it as a number
rather than an image-by-image side effect of normalization.

WHAT "GROUP" MEANS HERE
========================
HER2_IHC_40X carries no slide identifiers (see preprocessing/sources.py and
training/splits.py). The finest grouping this dataset supports is the 8-way
provenance group (slide score x train/test origin). Every function here
reports variation ACROSS PROVENANCE GROUPS, not across slides, and every
returned structure says so explicitly rather than calling a group a slide --
a report that quietly upgraded "provenance group" to "slide" would be the
same substitution training/splits.py was rewritten to stop making.

READING THE REPORT
====================
``between_group_mean_distance`` is only evidence of real stain variation if
it clearly exceeds ``within_group_mean_std_norm`` -- the ordinary spread of
stain estimates among patches that share a group. If the two are close, what
looks like "variation across groups" is indistinguishable from noise within
one group, and :attr:`StainVariationReport.summary`'s
``variation_exceeds_noise`` flag says so plainly rather than leaving a reader
to eyeball two numbers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from evaluation.stain_shift import descriptor_distance


@dataclass
class GroupStainStats:
    group: str
    n_patches: int
    mean_descriptor: list[float]
    std_descriptor: list[float]
    """Per-dimension std of the 6-value stain descriptor within this group."""

    def as_dict(self) -> dict:
        return {
            "group": self.group,
            "n_patches": self.n_patches,
            "mean_descriptor": self.mean_descriptor,
            "std_descriptor": self.std_descriptor,
            "std_descriptor_norm": round(float(np.linalg.norm(self.std_descriptor)), 6),
        }


@dataclass
class StainVariationReport:
    per_group: list[GroupStainStats]
    between_group_distances: dict[str, dict[str, float]]
    """group -> group -> Euclidean distance between mean descriptors."""

    within_group_mean_std_norm: float
    """Average, over groups, of the norm of that group's descriptor std."""

    between_group_mean_distance: float
    """Average, over all group pairs, of the distance between their means."""

    def summary(self) -> dict:
        return {
            "what_group_means": (
                "A provenance group (slide score x train/test origin), NOT a "
                "slide -- HER2_IHC_40X carries no slide identifiers. See "
                "training/splits.py."
            ),
            "n_groups": len(self.per_group),
            "within_group_mean_std_norm": round(self.within_group_mean_std_norm, 6),
            "between_group_mean_distance": round(self.between_group_mean_distance, 6),
            "variation_exceeds_noise": bool(
                self.between_group_mean_distance > self.within_group_mean_std_norm
            ),
            "per_group": [g.as_dict() for g in self.per_group],
            "between_group_distances": self.between_group_distances,
        }

    def write_json(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.summary(), fh, indent=2)


def compute_group_stats(descriptors_by_group: dict[str, np.ndarray]) -> list[GroupStainStats]:
    """Mean and std of the stain descriptor within each group."""
    stats = []
    for group, descriptors in sorted(descriptors_by_group.items()):
        array = np.asarray(descriptors, dtype=np.float64)
        if array.ndim != 2 or array.shape[0] == 0:
            raise ValueError(f"Group {group!r} has no descriptors to summarize.")
        stats.append(
            GroupStainStats(
                group=group,
                n_patches=int(array.shape[0]),
                mean_descriptor=array.mean(axis=0).tolist(),
                std_descriptor=array.std(axis=0).tolist(),
            )
        )
    return stats


def build_variation_report(descriptors_by_group: dict[str, np.ndarray]) -> StainVariationReport:
    """The full cross-group report, from raw per-patch descriptors.

    ``descriptors_by_group`` maps a provenance group name to an (n, 6) array
    of that group's per-patch stain descriptors (see
    :func:`evaluation.stain_shift.patch_stain_descriptor`).
    """
    if len(descriptors_by_group) < 2:
        raise ValueError(
            "Need at least two groups to report variation ACROSS groups; got "
            f"{len(descriptors_by_group)}."
        )
    per_group = compute_group_stats(descriptors_by_group)
    means = {g.group: np.asarray(g.mean_descriptor) for g in per_group}

    distances: dict[str, dict[str, float]] = {}
    all_pairs: list[float] = []
    for a in per_group:
        distances[a.group] = {}
        for b in per_group:
            if a.group == b.group:
                continue
            d = descriptor_distance(means[a.group], means[b.group])
            distances[a.group][b.group] = round(d, 6)
            all_pairs.append(d)

    within = float(np.mean([np.linalg.norm(g.std_descriptor) for g in per_group]))
    between = float(np.mean(all_pairs)) if all_pairs else 0.0

    return StainVariationReport(
        per_group=per_group,
        between_group_distances=distances,
        within_group_mean_std_norm=within,
        between_group_mean_distance=between,
    )
