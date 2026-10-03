"""Invasive-tumour detection that works on HER2 IHC, trained on public H&E annotations.

The problem: ASCO/CAP scores only INVASIVE tumour cells, but no public HER2
IHC data set has tumour outlines. Large expert-annotated sets exist for H&E
(TIGER: invasive tumour, in-situ tumour, stroma, normal glands, ...).

The bridge, this project's approach: both stains share haematoxylin. Nuclear
size, crowding and tissue architecture -- what separates invasive carcinoma
from stroma, normal glands and DCIS -- live in the haematoxylin channel.
Eosin (H&E) and DAB (IHC) do not carry that information and, for HER2,
DAB actively misleads (it varies with HER2 status, not tumour-ness). So the
segmenter sees a HAEMATOXYLIN-ONLY image:

1. colour-deconvolve with the stain's own vectors (H&E or H-DAB, Ruifrok &
   Johnston 2001);
2. normalise the haematoxylin concentration by its 99th percentile in tissue
   (removes lab-to-lab counterstain strength);
3. re-render it as a standard haematoxylin-blue RGB image.

An H&E region and an IHC region of the same tissue then look alike to the
network, so a model trained on H&E annotations can be applied to IHC. How
well this transfers is measured, not assumed (scripts/train_tumour.py,
docs/WHOLE_SLIDE.md).

Classes (TIGER labels folded): 0 other tissue (stroma, inflamed stroma,
necrosis, rest), 1 invasive tumour, 2 in-situ tumour, 3 healthy glands.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from preprocessing.stains import build_stain_matrix, od_to_rgb, rgb_to_od

TUMOUR_CLASSES = ("other tissue", "invasive tumour", "in-situ tumour", "healthy glands")
TUMOUR_MPP = 0.5  # TIGER's resolution; the segmenter always runs here
# TIGER mask values -> our classes; 0 (unannotated) -> ignore
TIGER_TO_OURS = {1: 1, 2: 0, 3: 2, 4: 3, 5: 0, 6: 0, 7: 0}
IGNORE = 255

H_HE = (0.644, 0.717, 0.267)      # Ruifrok H&E haematoxylin
EOSIN = (0.093, 0.954, 0.283)     # Ruifrok eosin
H_DAB = (0.650, 0.704, 0.286)     # Ruifrok H-DAB haematoxylin
DAB = (0.268, 0.570, 0.776)
H_TARGET_P99 = 1.0                # normalised haematoxylin level after rescaling


def white_balance(rgb: np.ndarray, floor: float = 120.0) -> np.ndarray:
    """Rescale each channel so the brightest pixels (99.5th percentile) become white.

    Deconvolution assumes white incident light (I0 = 255). Scans with a grey or
    tinted cast (dim illumination, unbalanced camera -- e.g. many BCI images)
    otherwise turn that neutral absorbance into "haematoxylin" everywhere and
    the segmenter sees a flat purple field. On a normal scan with white glass
    this is a no-op. ``floor`` stops an all-tissue image from being stretched
    as if its brightest tissue were glass.
    """
    white = np.maximum(np.percentile(rgb.reshape(-1, 3), 99.5, axis=0), floor)
    return np.clip(rgb.astype(np.float32) * (255.0 / white), 0, 255).astype(np.uint8)


def haematoxylin_image(rgb: np.ndarray, stain: str = "ihc", h_scale: float = 1.0, tissue: np.ndarray | None = None) -> np.ndarray:
    """RGB (H&E or H-DAB) -> haematoxylin-only RGB rendering, uint8."""
    matrix = build_stain_matrix(H_HE, EOSIN) if stain == "he" else build_stain_matrix(H_DAB, DAB)
    od = rgb_to_od(white_balance(rgb))
    conc = od.reshape(-1, 3) @ np.linalg.pinv(matrix)
    h = np.clip(conc[:, 0], 0, None).reshape(rgb.shape[:2])
    ref = h[tissue] if tissue is not None and tissue.any() else h[h > 0.05]
    p99 = float(np.percentile(ref, 99)) if ref.size > 100 else 1.0
    h = h * (H_TARGET_P99 / max(p99, 1e-3)) * h_scale
    standard = build_stain_matrix(H_DAB, DAB)[0]
    return od_to_rgb(h[..., None] * standard[None, None, :])


def build_segmenter(encoder: str = "resnet50", encoder_weights: str | None = "lunit_bt"):
    """U-Net (models/unet_seg.py) on 3-channel haematoxylin images, 4 tissue classes."""
    from models.unet_seg import ResNetUNet

    return ResNetUNet(num_classes=len(TUMOUR_CLASSES), pretrained=encoder_weights is not None, encoder=encoder,
                      encoder_weights=encoder_weights, in_channels=3)


def _standardize(x: torch.Tensor, weights: str | None) -> torch.Tensor:
    from models.unet_seg import rgb_statistics

    mean, std = rgb_statistics(weights)
    m = torch.tensor(mean, device=x.device).view(1, 3, 1, 1)
    s = torch.tensor(std, device=x.device).view(1, 3, 1, 1)
    return (x - m) / s


class TumourSegmenter:
    """Inference wrapper: RGB at TUMOUR_MPP -> per-pixel class probabilities."""

    def __init__(self, checkpoint: str | Path, device: str = "cpu") -> None:
        ck = torch.load(checkpoint, map_location="cpu", weights_only=False)
        cfg = ck.get("model_config", {})
        self.weights = cfg.get("encoder_weights")
        self.model = build_segmenter(cfg.get("encoder", "resnet50"), None)
        self.model.load_state_dict(ck["model_state"])
        self.device = torch.device(device)
        self.model.to(self.device).eval()
        self.info = {"checkpoint": str(checkpoint), "encoder": cfg.get("encoder"), "metrics": ck.get("metrics", {})}

    @torch.no_grad()
    def predict(self, rgb: np.ndarray, stain: str = "ihc", tile: int = 512) -> np.ndarray:
        """(H, W, 4) softmax probabilities for an RGB region at 0.5 um/px."""
        h_img = haematoxylin_image(rgb, stain)
        H, W = rgb.shape[:2]
        ph, pw = -(-H // tile) * tile, -(-W // tile) * tile
        canvas = np.full((ph, pw, 3), 255, dtype=np.uint8)
        canvas[:H, :W] = h_img
        x = torch.from_numpy(canvas).permute(2, 0, 1)[None].float().div(255.0)
        out = np.zeros((ph, pw, len(TUMOUR_CLASSES)), dtype=np.float32)
        for y in range(0, ph, tile):
            for xx in range(0, pw, tile):
                t = _standardize(x[..., y:y + tile, xx:xx + tile].to(self.device), self.weights)
                p = F.softmax(self.model(t).float(), 1)[0].permute(1, 2, 0).cpu().numpy()
                out[y:y + tile, xx:xx + tile] = p
        return out[:H, :W]
