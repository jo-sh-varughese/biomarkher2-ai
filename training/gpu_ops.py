"""Torch versions of the pixel operations training needs, so they run on the GPU.

A rented GPU pod has few CPU cores. Decoding PNGs already uses them; doing
colour deconvolution, morphology and augmentation there too would leave the
GPU waiting. Everything per-pixel here is a batched tensor op instead.

Three groups:

* Pseudo-labels -- the same rule as preprocessing.pipeline (OD tissue mask +
  fixed DAB thresholds) so the segmentation decoder keeps learning the
  project's established target. The tissue mask reproduces detect_tissue's
  "od" method: OD floor, value/saturation gates and a disk-3 closing+opening.
  It skips the remove-small-objects/holes pass (connected components have no
  cheap batched GPU form). tests/test_gpu_ops.py measures the agreement with
  the CPU pipeline on real patches.
* Augmentation -- stain (H/DAB vector rotation and concentration scaling),
  brightness/contrast, blur, noise, resampling (scanner/compression proxy),
  flips/rotations and zoom.
* Site normalization -- evaluation.cross_site.normalize_to_site, batched.

STAIN-STRENGTH AUGMENTATION IS DELIBERATELY MODERATE
====================================================
HER2 is scored by how DARK the DAB is. Scaling DAB by 0.4 turns a 3+ field
into something that genuinely looks 1+, so aggressive intensity jitter would
teach the model that intensity carries no information. Hue (stain-vector
direction) is jittered strongly, since it is pure site noise. Concentration
is jittered moderately (DAB x0.75-1.3 by default). Large lab-level offsets
are left to site-level normalization at inference and to multi-site training.
"""

from __future__ import annotations

import math

import torch
import torch.nn.functional as F

RUIFROK_H = (0.650, 0.704, 0.286)
RUIFROK_DAB = (0.268, 0.570, 0.776)


def stain_matrix(h=RUIFROK_H, dab=RUIFROK_DAB, device=None, dtype=torch.float32) -> torch.Tensor:
    h = torch.as_tensor(h, dtype=dtype, device=device)
    d = torch.as_tensor(dab, dtype=dtype, device=device)
    m = torch.stack([h, d, torch.linalg.cross(h, d)])
    return m / m.norm(dim=1, keepdim=True)


def rgb_to_od(rgb01: torch.Tensor) -> torch.Tensor:
    """(N,3,H,W) RGB in 0..1 -> optical density, same clipping as preprocessing.stains."""
    return -torch.log10(rgb01.clamp(1.0 / 255.0, 1.0))


def od_to_rgb(od: torch.Tensor) -> torch.Tensor:
    return torch.pow(10.0, -od).clamp(0.0, 1.0)


def concentrations(rgb01: torch.Tensor, matrix: torch.Tensor | None = None) -> torch.Tensor:
    """(N,3,H,W) -> (N,3,H,W) stain concentrations (H, DAB, residual), unclipped."""
    m = stain_matrix(device=rgb01.device) if matrix is None else matrix.to(rgb01.device, torch.float32)
    od = rgb_to_od(rgb01.float())
    return torch.einsum("nchw,cs->nshw", od, torch.linalg.pinv(m))


def dab_channel(rgb01: torch.Tensor) -> torch.Tensor:
    """(N,1,H,W) DAB optical density with the fixed Ruifrok vectors, clipped at 0."""
    return concentrations(rgb01)[:, 1:2].clamp_min(0.0)


def model_input(rgb01: torch.Tensor) -> torch.Tensor:
    """RGB (0..1) -> the 4-channel RGB+DAB tensor the U-Net takes."""
    return torch.cat([rgb01, dab_channel(rgb01).to(rgb01.dtype)], dim=1)


# --------------------------------------------------------------------------
# Pseudo-labels
# --------------------------------------------------------------------------


def _disk(radius: int, device) -> torch.Tensor:
    r = torch.arange(-radius, radius + 1, device=device, dtype=torch.float32)
    return ((r[:, None] ** 2 + r[None, :] ** 2) <= radius * radius).float()


def _dilate(mask: torch.Tensor, kernel: torch.Tensor) -> torch.Tensor:
    k = kernel[None, None]
    return F.conv2d(mask, k, padding=kernel.shape[-1] // 2) > 0.5


def _erode(mask: torch.Tensor, kernel: torch.Tensor) -> torch.Tensor:
    k = kernel[None, None]
    # Pad with 1 so the border does not erode inward (skimage's binary
    # erosion treats out-of-image pixels as True for this purpose).
    padded = F.pad(mask, [kernel.shape[-1] // 2] * 4, value=1.0)
    return F.conv2d(padded, k) > kernel.sum() - 0.5


def tissue_mask(rgb01: torch.Tensor, tissue_cfg) -> torch.Tensor:
    """(N,3,H,W) -> (N,H,W) bool, mirroring preprocessing.tissue.detect_tissue's "od" method."""
    rgb = rgb01.float()
    density = rgb_to_od(rgb).mean(1)
    value = rgb.amax(1)
    minimum = rgb.amin(1)
    saturation = torch.where(value > 0, (value - minimum) / value.clamp_min(1e-8), torch.zeros_like(value))
    mask = (
        (density >= float(tissue_cfg.od_floor))
        & (value <= float(tissue_cfg.value_ceiling))
        & (value >= float(tissue_cfg.value_floor))
        & (saturation >= float(tissue_cfg.achromatic_floor))
    )
    radius = int(tissue_cfg.morph_radius)
    if radius > 0:
        k = _disk(radius, rgb.device)
        m = mask[:, None].float()
        m = _erode(_dilate(m, k).float(), k).float()       # closing
        m = _dilate(_erode(m, k).float(), k)               # opening
        mask = m[:, 0]
    return mask


def pseudo_labels(rgb01: torch.Tensor, tissue_cfg, stain_cfg) -> torch.Tensor:
    """(N,3,H,W) -> (N,H,W) long: 0 background, 1 negative, 2 weak, 3 moderate, 4 strong."""
    mask = tissue_mask(rgb01, tissue_cfg)
    dab = dab_channel(rgb01)[:, 0]
    weak, moderate, strong = stain_cfg.thresholds()
    labels = torch.zeros_like(dab, dtype=torch.long)
    labels[mask] = 1
    labels[mask & (dab >= weak)] = 2
    labels[mask & (dab >= moderate)] = 3
    labels[mask & (dab >= strong)] = 4
    return labels


# --------------------------------------------------------------------------
# Augmentation
# --------------------------------------------------------------------------


def _rand(n, low, high, device):
    return torch.empty(n, device=device).uniform_(low, high)


def _rotate_towards(vec: torch.Tensor, angle: torch.Tensor) -> torch.Tensor:
    """Rotate unit vectors (N,3) by `angle` radians toward a random perpendicular direction."""
    rnd = torch.randn_like(vec)
    perp = rnd - (rnd * vec).sum(-1, keepdim=True) * vec
    perp = perp / perp.norm(dim=-1, keepdim=True).clamp_min(1e-8)
    out = vec * torch.cos(angle)[:, None] + perp * torch.sin(angle)[:, None]
    return out.abs() / out.abs().norm(dim=-1, keepdim=True)


def stain_augment(rgb01: torch.Tensor, cfg: dict) -> torch.Tensor:
    """Per-image random stain: rotate H/DAB vectors, scale and shift concentrations."""
    n, device = rgb01.shape[0], rgb01.device
    base = stain_matrix(device=device)
    conc = concentrations(rgb01)
    max_angle = math.radians(float(cfg.get("vector_degrees", 8.0)))
    h_vec = _rotate_towards(base[0].expand(n, 3), _rand(n, 0.0, max_angle, device))
    d_vec = _rotate_towards(base[1].expand(n, 3), _rand(n, 0.0, max_angle, device))
    resid = torch.linalg.cross(h_vec, d_vec)
    resid = resid / resid.norm(dim=-1, keepdim=True).clamp_min(1e-8)
    matrices = torch.stack([h_vec, d_vec, resid], dim=1)  # (N,3,3)

    h_scale = _rand(n, *cfg.get("h_scale", (0.7, 1.4)), device)
    d_scale = _rand(n, *cfg.get("dab_scale", (0.75, 1.3)), device)
    shift = float(cfg.get("shift", 0.03))
    scale = torch.stack([h_scale, d_scale, torch.ones_like(h_scale)], 1)[:, :, None, None]
    offset = torch.stack([_rand(n, -shift, shift, device), _rand(n, -shift, shift, device), torch.zeros(n, device=device)], 1)[:, :, None, None]
    tissue = (conc[:, :2].sum(1, keepdim=True) > 0.05).float()  # do not tint bare glass
    conc = conc * scale + offset * tissue
    od = torch.einsum("nshw,nsc->nchw", conc, matrices)
    return od_to_rgb(od)


def colour_augment(rgb01: torch.Tensor, cfg: dict) -> torch.Tensor:
    n, device = rgb01.shape[0], rgb01.device
    b = _rand(n, -cfg.get("brightness", 0.06), cfg.get("brightness", 0.06), device)[:, None, None, None]
    c = _rand(n, 1 - cfg.get("contrast", 0.1), 1 + cfg.get("contrast", 0.1), device)[:, None, None, None]
    mean = rgb01.mean((1, 2, 3), keepdim=True)
    return ((rgb01 - mean) * c + mean + b).clamp(0, 1)


def blur_noise_resample(rgb01: torch.Tensor, cfg: dict) -> torch.Tensor:
    """Scanner/compression proxies: Gaussian blur, sensor noise, down-up resampling."""
    out = rgb01
    n, device = out.shape[0], out.device
    p = float(cfg.get("p", 0.3))
    if p <= 0:
        return out
    sel = torch.rand(n, device=device) < p
    if sel.any():
        sigma = float(_rand(1, 0.4, cfg.get("max_sigma", 1.2), device))
        radius = max(1, int(math.ceil(2 * sigma)))
        x = torch.arange(-radius, radius + 1, device=device, dtype=out.dtype)
        k = torch.exp(-(x ** 2) / (2 * sigma * sigma))
        k = k / k.sum()
        blurred = F.conv2d(F.pad(out[sel], [radius, radius, 0, 0], mode="reflect"), k.view(1, 1, 1, -1).expand(3, 1, 1, -1), groups=3)
        blurred = F.conv2d(F.pad(blurred, [0, 0, radius, radius], mode="reflect"), k.view(1, 1, -1, 1).expand(3, 1, -1, 1), groups=3)
        out = out.clone()
        out[sel] = blurred
    sel = torch.rand(n, device=device) < p
    if sel.any():
        out = out.clone()
        out[sel] = (out[sel] + torch.randn_like(out[sel]) * float(cfg.get("noise", 0.02))).clamp(0, 1)
    sel = torch.rand(n, device=device) < p
    if sel.any():
        h, w = out.shape[-2:]
        f = float(_rand(1, 0.5, 0.85, device))
        small = F.interpolate(out[sel], scale_factor=f, mode="bilinear", align_corners=False, antialias=True)
        out = out.clone()
        out[sel] = F.interpolate(small, size=(h, w), mode="bilinear", align_corners=False).clamp(0, 1)
    return out


def flip_rotate(images: torch.Tensor, labels: torch.Tensor | None):
    """Same random dihedral transform for each image and its label map."""
    k = int(torch.randint(0, 4, (1,)))
    flip = bool(torch.randint(0, 2, (1,)))
    images = torch.rot90(images, k, dims=(-2, -1))
    if labels is not None:
        labels = torch.rot90(labels, k, dims=(-2, -1))
    if flip:
        images = images.flip(-1)
        if labels is not None:
            labels = labels.flip(-1)
    return images, labels


def zoom(images: torch.Tensor, labels: torch.Tensor | None, factor: float, size: int):
    """Rescale by `factor`, then centre-crop or white-pad back to `size` (labels padded as background)."""
    if abs(factor - 1.0) < 1e-3:
        return images, labels
    new = max(8, int(round(images.shape[-1] * factor)))
    images = F.interpolate(images, size=(new, new), mode="bilinear", align_corners=False, antialias=factor < 1)
    if labels is not None:
        labels = F.interpolate(labels[:, None].float(), size=(new, new), mode="nearest")[:, 0].long()
    if new >= size:
        off = (new - size) // 2
        images = images[..., off:off + size, off:off + size]
        if labels is not None:
            labels = labels[..., off:off + size, off:off + size]
    else:
        pad = size - new
        a, b = pad // 2, pad - pad // 2
        images = F.pad(images, [a, b, a, b], value=1.0)
        if labels is not None:
            labels = F.pad(labels, [a, b, a, b], value=0)
    return images, labels


def to_tiles(images: torch.Tensor, tile: int) -> torch.Tensor:
    """(N,C,H,W) -> (N*(H/tile)*(W/tile), C, tile, tile), row-major per image."""
    n, c, h, w = images.shape
    x = images.reshape(n, c, h // tile, tile, w // tile, tile)
    return x.permute(0, 2, 4, 1, 3, 5).reshape(-1, c, tile, tile)


def label_tiles(labels: torch.Tensor, tile: int) -> torch.Tensor:
    return to_tiles(labels[:, None], tile)[:, 0]


# --------------------------------------------------------------------------
# Site normalization (batched evaluation.cross_site.normalize_to_site)
# --------------------------------------------------------------------------


def normalize_to_site(rgb01: torch.Tensor, target: dict, reference: dict) -> torch.Tensor:
    """Per-stain site-level normalization with profiles as saved in site_profiles.json."""
    device = rgb01.device
    tm = torch.tensor(target["stain_matrix"], dtype=torch.float32, device=device)
    rm = torch.tensor(reference["stain_matrix"], dtype=torch.float32, device=device)
    scale = torch.tensor(reference["concentration_p99"], device=device) / torch.tensor(target["concentration_p99"], device=device).clamp_min(1e-6)
    conc = concentrations(rgb01, tm)
    conc = conc * torch.cat([scale, torch.ones(1, device=device)]).view(1, 3, 1, 1)
    return od_to_rgb(torch.einsum("nshw,sc->nchw", conc, rm))
