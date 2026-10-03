"""Site fingerprint: measure how a new hospital's images differ from ours.

Run on a folder of UNLABELLED images from a new site (a few dozen is enough).
It measures the acquisition and staining properties that decide whether, and
how, the model's input must be corrected, and compares them with the training
site's fingerprint:

* **Magnification**, from the scanner's microns-per-pixel when known (whole
  slide images record it; pass ``site_mpp``/``reference_mpp`` to ``compare``).
  A nucleus-size estimate (self-calibrated against our own images shrunk by
  known factors) is reported as a LOW-CONFIDENCE cross-check only and is never
  applied automatically: on BCI it read x6 where the published pixel sizes
  give x1.9, and a direct test confirmed x2 is right (x2 43.1%, x3 42.0%,
  x4 38.8% accuracy) -- blur and JPEG texture fool blob detectors.
* **Sharpness** (variance of the Laplacian, measured after rescaling to our
  scale, so it compares like with like) -- focus quality.
* **Compression**: file format, and for JPEG an estimated quality from its
  quantization table.
* **Noise** (high-frequency energy on bare glass) and **background
  brightness** (white balance / illumination).
* **Staining**: pooled H and DAB stain vectors and concentration percentiles
  (evaluation/cross_site.py), plus the stained-tissue fraction.

``compare`` turns two fingerprints into the corrections the pipeline applies
(resize factor, stain normalization, label-free DAB scale) and plain-language
flags for anything outside what the model was trained on.
"""

from __future__ import annotations

import io
import math
from pathlib import Path

import numpy as np
from PIL import Image

from evaluation.cross_site import fit_site_profile, sample_tissue_pixels
from preprocessing.stains import deconvolve
from preprocessing.tissue import detect_tissue

# IJG standard luminance quantization table (quality 50), natural order.
_STD_LUMA = np.array([
    16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56,
    14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99], dtype=float)
_ZIGZAG = np.array([
    0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21,
    28, 35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61,
    54, 47, 55, 62, 63])


def jpeg_quality(image: Image.Image) -> float | None:
    """Estimated IJG quality (1-100) from the luminance table; None if not JPEG."""
    tables = getattr(image, "quantization", None)
    if not tables or 0 not in tables:
        return None
    luma = np.array(list(tables[0])[:64], dtype=float)  # Pillow returns natural (row-major) order
    scale = float(np.mean(luma / _STD_LUMA) * 100.0)
    quality = (200.0 - scale) / 2.0 if scale <= 100 else 5000.0 / scale
    return float(np.clip(quality, 1, 100))


SCALE_GRID = (1.0, 1.5, 2.0, 3.0, 4.0, 6.0)


def nucleus_diameter(rgb: np.ndarray, tissue: np.ndarray) -> float | None:
    """Apparent nucleus size (px): median scale of Laplacian-of-Gaussian blobs in the haematoxylin channel.

    The raw number is biased (small blobs hit the detector's resolution
    limit), so it is never used directly as a magnification ratio -- see
    ``scale_curve`` / ``estimate_resize_factor``, which calibrate it.
    """
    from skimage.feature import blob_log

    if tissue.sum() < 1000:
        return None
    h = np.where(tissue, deconvolve(rgb)[..., 0], 0.0)
    h = np.clip(h / max(1e-6, float(np.percentile(h[tissue], 99))), 0, 1)
    blobs = blob_log(h, min_sigma=1.0, max_sigma=25, num_sigma=40, log_scale=True, threshold=0.08, overlap=0.5)
    if len(blobs) < 5:
        return None
    return float(np.median(blobs[:, 2]) * 2 * math.sqrt(2))


def _centre(rgb: np.ndarray, size: int = 512) -> np.ndarray:
    h, w = rgb.shape[:2]
    top, left = max(0, (h - size) // 2), max(0, (w - size) // 2)
    return rgb[top:top + size, left:left + size]


def scale_curve(reference_paths, prep, grid=SCALE_GRID, max_images: int = 12) -> dict:
    """Apparent nucleus size of OUR images after shrinking them by each factor in ``grid``.

    Self-calibration: whatever bias the blob detector has at low resolution,
    our own images show it identically, so a new site's apparent size can be
    read off this curve as a magnification factor.
    """
    out = {}
    for f in grid:
        vals = []
        for p in list(reference_paths)[:max_images]:
            im = Image.open(p).convert("RGB")
            if f != 1.0:
                im = im.resize((max(64, int(im.width / f)), max(64, int(im.height / f))), Image.LANCZOS)
            rgb = _centre(np.asarray(im))
            d = nucleus_diameter(rgb, detect_tissue(rgb, prep.tissue))
            if d:
                vals.append(d)
        if vals:
            out[str(f)] = float(np.median(vals))
    return out


def estimate_resize_factor(site_diameter: float, curve: dict) -> float:
    """Interpolate (in log space) the factor at which our images look like the site's."""
    pts = sorted(((float(f), d) for f, d in curve.items()), key=lambda t: t[0])
    fs = np.log([p[0] for p in pts])
    ds = np.log([p[1] for p in pts])
    order = np.argsort(ds)  # diameter falls as the factor rises
    return float(np.exp(np.interp(math.log(site_diameter), ds[order], fs[order])))


def _laplacian_var(grey: np.ndarray) -> float:
    from scipy import ndimage

    return float(ndimage.laplace(grey).var())


def image_fingerprint(path: str | Path, prep) -> dict:
    image = Image.open(path)
    fmt, quality = image.format, jpeg_quality(image)
    rgb = np.asarray(image.convert("RGB"))
    tissue = detect_tissue(rgb, prep.tissue)
    centre = _centre(rgb)
    nucleus = nucleus_diameter(centre, detect_tissue(centre, prep.tissue))
    grey = rgb.astype(float).mean(-1)
    glass = ~tissue
    from scipy import ndimage

    noise = float(np.std(ndimage.laplace(grey)[glass])) if glass.sum() > 1000 else None
    conc = deconvolve(rgb)
    return {
        "path": str(path), "format": fmt, "jpeg_quality": quality, "size": list(rgb.shape[:2]),
        "tissue_fraction": float(tissue.mean()),
        "nucleus_diameter_px": nucleus,
        "sharpness_native": _laplacian_var(grey),
        "noise_on_glass": noise,
        "background_rgb": rgb[glass].mean(0).round(1).tolist() if glass.sum() > 1000 else None,
        "dab_positive_fraction": float((conc[..., 1][tissue] >= prep.stain.thresholds()[0]).mean()) if tissue.any() else 0.0,
    }


def site_fingerprint(paths: list[str | Path], prep, max_images: int = 60, max_pixels: int = 20000, seed: int = 0,
                     with_scale_curve: bool = False) -> dict:
    """Pooled fingerprint of up to ``max_images`` images from one site.

    ``with_scale_curve`` (for the TRAINING site) also stores the
    self-calibration curve that magnification estimates are read from.
    """
    rng = np.random.default_rng(seed)
    paths = list(paths)
    if len(paths) > max_images:
        paths = [paths[i] for i in sorted(rng.choice(len(paths), max_images, replace=False))]
    per_image, samples = [], []
    for p in paths:
        fp = image_fingerprint(p, prep)
        per_image.append(fp)
        rgb = np.asarray(Image.open(p).convert("RGB"))
        mask = detect_tissue(rgb, prep.tissue)
        if mask.sum() >= 1000:
            samples.append(sample_tissue_pixels(rgb, mask, max_pixels, rng))

    def med(key):
        vals = [f[key] for f in per_image if f.get(key) is not None]
        return float(np.median(vals)) if vals else None

    profile = fit_site_profile(samples) if samples else None
    backgrounds = [f["background_rgb"] for f in per_image if f.get("background_rgb")]
    return {
        "n_images": len(per_image),
        "formats": sorted({str(f["format"]) for f in per_image}),
        "jpeg_quality": med("jpeg_quality"),
        "image_size": per_image[0]["size"] if per_image else None,
        "nucleus_diameter_px": med("nucleus_diameter_px"),
        "sharpness_native": med("sharpness_native"),
        "noise_on_glass": med("noise_on_glass"),
        "background_rgb": np.median(np.array(backgrounds), 0).round(1).tolist() if backgrounds else None,
        "tissue_fraction": med("tissue_fraction"),
        "dab_positive_fraction": med("dab_positive_fraction"),
        "stain_profile": profile.to_dict() if profile else None,
        "scale_curve": scale_curve(paths, prep) if with_scale_curve else None,
    }


def _angle(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float(np.degrees(np.arccos(np.clip(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)), -1, 1))))


def compare(site: dict, reference: dict, site_mpp: float | None = None, reference_mpp: float | None = None) -> dict:
    """Corrections to apply to ``site`` so it looks like ``reference``, plus flags."""
    out: dict = {"corrections": {}, "measurements": {}, "flags": []}
    m, c, flags = out["measurements"], out["corrections"], out["flags"]

    if site_mpp and reference_mpp:
        factor = site_mpp / reference_mpp
        c["resize_factor"] = round(factor, 3)
        m["microns_per_pixel"] = [site_mpp, reference_mpp]
        if abs(math.log(factor)) > math.log(1.15):
            flags.append(f"Magnification differs ({site_mpp} vs {reference_mpp} um/px): images will be enlarged x{factor:.2f}.")
    else:
        c["resize_factor"] = None
        flags.append("Scanner microns-per-pixel unknown: confirm magnification before scoring.")
    if site.get("nucleus_diameter_px") and reference.get("scale_curve"):
        estimate = estimate_resize_factor(site["nucleus_diameter_px"], reference["scale_curve"])
        m["nucleus_scale_estimate_low_confidence"] = round(estimate, 2)
        if c["resize_factor"] and abs(math.log(estimate / c["resize_factor"])) > math.log(1.5):
            flags.append(f"Nucleus-size cross-check (x{estimate:.1f}) disagrees with scanner metadata (x{c['resize_factor']:.2f}): "
                         "check focus/image quality.")

    if site.get("jpeg_quality") is not None:
        m["jpeg_quality"] = site["jpeg_quality"]
        if site["jpeg_quality"] < 80:
            flags.append(f"Strong JPEG compression (quality ~{site['jpeg_quality']:.0f}); fine membrane detail may be lost.")

    if site.get("sharpness_native") and reference.get("sharpness_native"):
        # sharpness after enlarging falls roughly with the square of the factor; compare at the training scale
        rescaled = site["sharpness_native"] / max(1e-6, (c["resize_factor"] or 1.0) ** 2)
        m["sharpness_at_training_scale"] = [round(rescaled, 2), round(reference["sharpness_native"], 2)]
        if rescaled < 0.15 * reference["sharpness_native"]:
            flags.append("Images are much blurrier than training images, even allowing for magnification.")

    sp, rp = site.get("stain_profile"), reference.get("stain_profile")
    if sp and rp:
        h_angle = _angle(sp["stain_matrix"][0], rp["stain_matrix"][0])
        d_angle = _angle(sp["stain_matrix"][1], rp["stain_matrix"][1])
        dab_ratio = rp["concentration_p99"][1] / max(1e-6, sp["concentration_p99"][1])
        h_ratio = rp["concentration_p99"][0] / max(1e-6, sp["concentration_p99"][0])
        m.update({"haematoxylin_vector_angle_deg": round(h_angle, 1), "dab_vector_angle_deg": round(d_angle, 1),
                  "dab_strength_ratio": round(dab_ratio, 3), "haematoxylin_strength_ratio": round(h_ratio, 3)})
        c["stain_normalization"] = {"target": sp, "reference": rp}
        c["dab_scale_label_free"] = round(dab_ratio, 3)
        if dab_ratio > 1.4 or dab_ratio < 0.7:
            flags.append(f"DAB staining is {'weaker' if dab_ratio > 1 else 'stronger'} than in training (x{1 / dab_ratio:.2f}); "
                         f"site-level DAB correction x{dab_ratio:.2f} will be applied.")
        if max(h_angle, d_angle) > 10:
            flags.append(f"Stain colours differ (H {h_angle:.0f} deg, DAB {d_angle:.0f} deg apart); stain vectors will be remapped.")

    if site.get("background_rgb") and reference.get("background_rgb"):
        diff = float(np.abs(np.array(site["background_rgb"]) - np.array(reference["background_rgb"])).max())
        m["background_rgb"] = [site["background_rgb"], reference["background_rgb"]]
        if diff > 15:
            flags.append(f"Background brightness/white balance differs by up to {diff:.0f}/255.")
    return out
