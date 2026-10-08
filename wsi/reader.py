"""Whole-slide image access: any scanner format OpenSlide reads, plus plain images.

OpenSlide (openslide-python + the ``openslide-bin`` wheel, which ships the
native library on Windows, macOS and Linux) reads Aperio .svs, Hamamatsu
.ndpi, MIRAX .mrxs, Leica .scn, Philips TIFF, Ventana BIF and generic
pyramidal TIFF. Ordinary images (.png/.jpg/small .tif) open through
``openslide.ImageSlide`` so every slide, large or small, has one interface.

Everything downstream asks for pixels at a PHYSICAL resolution (microns per
pixel), never at a pyramid level: the pre-score model expects ~0.24 um/px,
the control and ink checks 0.5-2 um/px, the overview ~8 um/px, and which pyramid
level serves each best depends on the scanner.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

SLIDE_SUFFIXES = (".svs", ".ndpi", ".mrxs", ".scn", ".tif", ".tiff", ".bif", ".vms", ".vmu", ".svslide", ".png", ".jpg", ".jpeg")


@dataclass(frozen=True)
class SlideInfo:
    path: str
    width: int
    height: int
    mpp: float | None
    """Microns per pixel at level 0, from scanner metadata (None if the file does not record it)."""
    levels: int
    vendor: str
    objective_power: float | None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class Slide:
    def __init__(self, path: str | Path, mpp_override: float | None = None) -> None:
        import openslide

        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(f"No slide at {self.path}")
        try:
            self._slide = openslide.OpenSlide(str(self.path))
            vendor = self._slide.properties.get(openslide.PROPERTY_NAME_VENDOR, "unknown")
        except openslide.OpenSlideUnsupportedFormatError:
            self._slide = openslide.ImageSlide(str(self.path))
            vendor = "image"
        props = self._slide.properties
        mpp = mpp_override
        if mpp is None:
            raw = props.get("openslide.mpp-x")
            mpp = float(raw) if raw not in (None, "", "0") else None
        power = props.get("openslide.objective-power")
        w, h = self._slide.dimensions
        self.info = SlideInfo(str(self.path), int(w), int(h), mpp, int(self._slide.level_count), vendor,
                              float(power) if power not in (None, "") else None)

    # ------------------------------------------------------------------ reads
    def _level_for(self, downsample: float) -> int:
        return int(self._slide.get_best_level_for_downsample(max(1.0, downsample)))

    def read(self, x: int, y: int, w: int, h: int, target_mpp: float | None = None) -> np.ndarray:
        """RGB uint8 for the level-0 box (x, y, w, h), resampled to ``target_mpp`` (None = native)."""
        native = self.info.mpp
        scale = 1.0 if (target_mpp is None or native is None) else target_mpp / native  # >1: shrink
        level = self._level_for(scale)
        ds = float(self._slide.level_downsamples[level])
        lw, lh = max(1, int(round(w / ds))), max(1, int(round(h / ds)))
        region = self._slide.read_region((int(x), int(y)), level, (lw, lh))
        rgb = Image.new("RGB", region.size, (255, 255, 255))
        rgb.paste(region, mask=region.split()[3])  # transparent = outside the scanned area = glass
        out_w, out_h = max(1, int(round(w / scale))), max(1, int(round(h / scale)))
        if rgb.size != (out_w, out_h):
            rgb = rgb.resize((out_w, out_h), Image.LANCZOS if scale > ds else Image.BICUBIC)
        return np.asarray(rgb)

    def overview(self, target_mpp: float = 8.0, max_side: int = 4096) -> tuple[np.ndarray, float]:
        """Whole-slide image at ~target_mpp (capped at ``max_side``); returns (rgb, level-0 px per overview px)."""
        w, h = self.info.width, self.info.height
        factor = (target_mpp / self.info.mpp) if self.info.mpp else max(w, h) / 2048
        factor = max(factor, max(w, h) / max_side, 1.0)
        thumb = self._slide.get_thumbnail((int(w / factor), int(h / factor))).convert("RGB")
        return np.asarray(thumb), w / thumb.width

    def deepzoom(self, tile_size: int = 254, overlap: int = 1):
        from openslide.deepzoom import DeepZoomGenerator

        return DeepZoomGenerator(self._slide, tile_size=tile_size, overlap=overlap, limit_bounds=True)

    def close(self) -> None:
        self._slide.close()


def tissue_overview_mask(rgb: np.ndarray, min_area_px: int = 64) -> np.ndarray:
    """Tissue vs glass on a low-resolution overview (grey optical density + saturation, cleaned)."""
    from scipy import ndimage

    arr = rgb.astype(np.float64) / 255.0
    od = -np.log10(np.clip(arr, 1 / 255, 1)).mean(-1)
    mx, mn = arr.max(-1), arr.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    mask = (od > 0.06) & (sat > 0.04) & (mx < 0.95) & (mx > 0.05)
    mask = ndimage.binary_closing(mask, iterations=2)
    mask = ndimage.binary_opening(mask, iterations=1)
    labels, n = ndimage.label(mask)
    if n:
        sizes = np.bincount(labels.ravel())
        keep = sizes >= min_area_px
        keep[0] = False
        mask = keep[labels]
    return ndimage.binary_fill_holes(mask)


def list_slides(root: str | Path) -> list[dict]:
    """Slides under ``root`` with a stable id (relative path, '/'-separated)."""
    root = Path(root)
    if not root.is_dir():
        return []
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in SLIDE_SUFFIXES:
            out.append({"id": p.relative_to(root).as_posix(), "name": p.name, "size_mb": round(p.stat().st_size / 1e6, 1)})
    return out
