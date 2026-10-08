"""Decode an uploaded field image safely into 8-bit RGB.

Uploads come from many sources (scanner exports, camera on a microscope,
screenshots). Each of these has bitten a pipeline somewhere:

* not an image / truncated file -> a clear message, not a stack trace;
* a decompression bomb (tiny file, enormous pixel count) -> refused before decoding;
* 16-bit TIFF -> rescaled to 8 bits (PIL's plain convert("RGB") clips it to white);
* CMYK, palette, greyscale+alpha -> converted to RGB;
* transparency -> composited onto white glass, not onto black;
* EXIF rotation from a phone or microscope camera -> applied;
* multi-page TIFF -> the first page, with a note.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from app.field_quality import MAX_PIXELS


class ImageDecodeError(ValueError):
    """A message safe to show the user."""


def decode_upload(raw: bytes) -> tuple[np.ndarray, list[str]]:
    """(H x W x 3 uint8 RGB, notes) or ImageDecodeError."""
    notes: list[str] = []
    if not raw:
        raise ImageDecodeError("The uploaded file is empty.")
    try:
        im = Image.open(io.BytesIO(raw))
    except UnidentifiedImageError:
        raise ImageDecodeError("The file is not an image this tool can read (use PNG, JPEG or TIFF).") from None
    except Exception as exc:  # noqa: BLE001
        raise ImageDecodeError(f"The image could not be opened: {exc}") from None
    w, h = im.size
    if w * h > MAX_PIXELS:
        raise ImageDecodeError(f"The image is {w}x{h} px ({w * h / 1e6:.0f} megapixels); a single field may be at most "
                               f"{MAX_PIXELS / 1e6:.0f} megapixels. Analyse a whole slide from the Whole slides page instead.")
    if getattr(im, "n_frames", 1) > 1:
        notes.append(f"The file has {im.n_frames} pages; the first page was analysed.")
        im.seek(0)
    try:
        im.load()
    except Exception as exc:  # noqa: BLE001 - truncated or corrupt data
        raise ImageDecodeError(f"The image file is damaged or incomplete: {exc}") from None
    try:
        im = ImageOps.exif_transpose(im)
    except Exception:  # noqa: BLE001 - malformed EXIF must not block analysis
        pass
    if im.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
        a = np.asarray(im, dtype=np.float64)
        top = np.percentile(a, 99.9) or a.max() or 1.0
        a = np.clip(a / top * 255.0, 0, 255).astype(np.uint8)
        notes.append("The image was high bit-depth greyscale; it was rescaled to 8 bits.")
        return np.stack([a] * 3, -1), notes
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
        notes.append("Transparent areas were treated as empty glass.")
    rgb = np.asarray(im.convert("RGB"), dtype=np.uint8)
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ImageDecodeError("The image could not be converted to RGB.")
    return rgb, notes
