"""Hard-link a subset of a pseudo-label cache into a new cache directory.

    python scripts/subset_pseudo_label_cache.py \\
        --source data/cache/pseudo_labels_40x \\
        --dest data/cache/pseudo_labels_40x_orig \\
        --parents-from data/cache/pseudo_labels_40x/tiles.json

Why this exists. training/train.py draws its capped fit/val sample from the
patches that have tiles ON DISK, so a cache that grows between two runs
silently changes which patches the second run trains and validates on, even
with the same seed, split and config. pseudo_labels_40x grew by 3,662 tiles on
2026-09-17 without its tiles.json or manifest being rewritten, which is why the
baseline and class-weighted runs (792 fit tiles) are not on the same sample as
the ordinal run (786). Pointing a run at a subset that holds only the patches
of a reference tile index puts it back on the original pool.

Files are hard-linked, not copied (a copy is the fallback across volumes), so
the subset costs no disk. ``--parents-from`` is a tiles.json (parent patch id ->
tile ids). The tiles linked are the ones on disk in ``--source`` for each
parent, so one reference index can also restrict a sibling cache built from the
same patches (a threshold-variant cache, say) to the same pool.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.pseudo_labels import TILE_INDEX_NAME, PseudoLabelCache

PROVENANCE_NAME = "SUBSET.json"


def _link(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def subset_cache(source_root: str | Path, dest_root: str | Path, parent_ids) -> dict:
    """Link the tiles of ``parent_ids`` from one cache into a new one.

    Returns the parents and tile counts, and the parents that have no tiles in
    the source. Refuses a destination that already has content, so a subset is
    never silently mixed into an existing cache.
    """
    dest_path = Path(dest_root)
    if dest_path.exists() and any(dest_path.iterdir()):
        raise SystemExit(f"{dest_path} already exists and is not empty; refusing to mix into it.")

    source = PseudoLabelCache(source_root)
    dest = PseudoLabelCache(dest_root)
    index: dict[str, list[str]] = {}
    missing: list[str] = []

    for parent in sorted(set(parent_ids)):
        tiles = source.tile_ids(parent)
        if not tiles:
            missing.append(parent)
            continue
        for tile in tiles:
            for src, dst in zip(source.paths(tile), dest.paths(tile)):
                dst.parent.mkdir(parents=True, exist_ok=True)
                _link(src, dst)
        index[parent] = tiles

    dest_path.mkdir(parents=True, exist_ok=True)
    (dest_path / TILE_INDEX_NAME).write_text(json.dumps(index, indent=2), encoding="utf-8")
    result = {
        "source": str(source_root),
        "parents": len(index),
        "tiles": sum(len(tiles) for tiles in index.values()),
        "parents_missing_from_source": missing,
    }
    (dest_path / PROVENANCE_NAME).write_text(
        json.dumps(
            result | {"note": "A subset of the source cache. No manifest.csv or summary.json."},
            indent=2,
        ),
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--dest", required=True)
    parser.add_argument(
        "--parents-from",
        required=True,
        help="A tiles.json whose keys are the parent patch ids to keep.",
    )
    args = parser.parse_args()

    parents = json.loads(Path(args.parents_from).read_text(encoding="utf-8")).keys()
    result = subset_cache(args.source, args.dest, parents)
    print(f"Linked {result['tiles']} tiles from {result['parents']} parent patches into {args.dest}")
    if result["parents_missing_from_source"]:
        print(f"NOTE: {len(result['parents_missing_from_source'])} reference parents have no tiles in the source.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
