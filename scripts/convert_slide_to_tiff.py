"""Convert a whole-slide image (.mrxs, .ndpi, .svs, ...) to one pyramidal, tiled, JPEG-compressed .tiff.

    python scripts/convert_slide_to_tiff.py SRC.mrxs OUT.tiff [--no-crop] [--quality 85]

The output is a "generic tiled TIFF" that OpenSlide (and so the portal's Slides
page) reads directly: full resolution in the first directory, then 2x, 4x, ...
downsampled levels, 512 px JPEG tiles, and the microns-per-pixel written as the
TIFF resolution so the analysis knows the magnification. By default the image
is cropped to the tissue (plus a margin): a 40x MIRAX scan is mostly empty glass.
Needs tifffile and imagecodecs (pip install tifffile imagecodecs).
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import openslide
import tifffile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wsi.reader import tissue_overview_mask  # noqa: E402

TILE = 512


def tissue_box(slide: openslide.OpenSlide, margin_um: float = 500.0) -> tuple[int, int, int, int]:
    """(x, y, w, h) at level 0 around all tissue, found on a low-resolution level."""
    level = slide.level_count - 1
    while level > 0 and max(slide.level_dimensions[level]) < 1500:
        level -= 1
    ds = slide.level_downsamples[level]
    rgb = np.asarray(slide.read_region((0, 0), level, slide.level_dimensions[level]).convert("RGB"))
    mask = tissue_overview_mask(rgb)
    if not mask.any():
        return 0, 0, *slide.dimensions
    ys, xs = np.where(mask)
    mpp = float(slide.properties.get(openslide.PROPERTY_NAME_MPP_X, 0.25))
    m = margin_um / mpp
    x0, y0 = max(0, int(xs.min() * ds - m)), max(0, int(ys.min() * ds - m))
    x1 = min(slide.dimensions[0], int((xs.max() + 1) * ds + m))
    y1 = min(slide.dimensions[1], int((ys.max() + 1) * ds + m))
    return x0, y0, x1 - x0, y1 - y0


def tiles(slide: openslide.OpenSlide, level: int, box, shape, workers: int = 6):
    """Row-major 512x512 RGB tiles of ``level`` inside the level-0 ``box`` (white where there is no scan)."""
    x0, y0 = box[0], box[1]
    ds = slide.level_downsamples[level]
    h, w = shape
    coords = [(r, c) for r in range(0, h, TILE) for c in range(0, w, TILE)]

    def read(rc):
        r, c = rc
        im = slide.read_region((int(x0 + c * ds), int(y0 + r * ds)), level, (TILE, TILE))
        a = np.asarray(im)
        rgb = a[..., :3].copy()
        rgb[a[..., 3] == 0] = 255  # transparent (unscanned) -> white glass
        return rgb

    with ThreadPoolExecutor(workers) as pool:
        # bounded read-ahead keeps memory flat on a 30 Gpx slide
        for i in range(0, len(coords), workers * 8):
            yield from pool.map(read, coords[i:i + workers * 8])


def convert(src: Path, out: Path, crop: bool = True, quality: int = 85) -> None:
    slide = openslide.OpenSlide(str(src))
    mpp = float(slide.properties.get(openslide.PROPERTY_NAME_MPP_X, 0) or 0)
    box = tissue_box(slide) if crop else (0, 0, *slide.dimensions)
    print(f"{src.name}: level 0 {slide.dimensions}, mpp {mpp:.4f}, writing box {box}", flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")
    started = time.time()
    with tifffile.TiffWriter(tmp, bigtiff=True) as tif:
        level = 0
        while level < slide.level_count:
            ds = slide.level_downsamples[level]
            shape = (int(box[3] / ds), int(box[2] / ds))
            if level > 0 and max(shape) < 512:
                break
            kw = {}
            if mpp:
                res = 1e4 / (mpp * ds)  # pixels per centimetre
                kw = {"resolution": (res, res), "resolutionunit": "CENTIMETER"}
            tif.write(tiles(slide, level, box, shape), shape=(*shape, 3), dtype=np.uint8, tile=(TILE, TILE),
                      photometric="rgb", compression="jpeg", metadata=None, compressionargs={"level": quality},
                      subfiletype=0 if level == 0 else 1, description=f"source={src.name};mpp={mpp}" if level == 0 else None,
                      **kw)
            print(f"  level {level}: {shape[1]}x{shape[0]} ({time.time() - started:.0f}s)", flush=True)
            level += 1
    tmp.replace(out)
    print(f"  wrote {out} ({out.stat().st_size / 1e6:.0f} MB) in {time.time() - started:.0f}s", flush=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("src", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--no-crop", action="store_true", help="keep the whole scan, glass included")
    p.add_argument("--quality", type=int, default=85)
    a = p.parse_args()
    convert(a.src, a.out, crop=not a.no_crop, quality=a.quality)
    check = openslide.OpenSlide(str(a.out))
    print(f"  check: {check.dimensions}, {check.level_count} levels, mpp {check.properties.get('openslide.mpp-x')}, "
          f"vendor {check.properties.get('openslide.vendor')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
