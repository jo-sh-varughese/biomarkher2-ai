"""Real, code-backed preprocessing figures for the paper: stain
deconvolution and the Otsu-vs-optical-density tissue detection failure
mode, both run through this repo's actual preprocessing/ functions against
real HER2_IHC_40X patches (not synthetic illustrations).

    python make_preprocessing_figures.py
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from preprocessing.stains import dab_channel, hematoxylin_channel
from preprocessing.tissue import detect_tissue, grey_optical_density
from preprocessing.config import TissueConfig


def load(path: Path) -> np.ndarray:
    return np.array(Image.open(path).convert("RGB"))


# A strong (3+) patch shows the deconvolution clearly; a faint (class_0)
# patch is exactly where the Otsu-on-saturation failure mode bites hardest.
strong_dir = REPO_ROOT / "data/raw/test/class_3+"
faint_dir = REPO_ROOT / "data/raw/test/class_0"
strong_path = sorted(strong_dir.glob("*.png"))[0]
faint_path = sorted(faint_dir.glob("*.png"))[0]

# ---------------------------------------------------------------------
# Figure 1: stain deconvolution (RGB -> haematoxylin -> DAB)
# ---------------------------------------------------------------------
rgb = load(strong_path)
h_map = hematoxylin_channel(rgb)
dab_map = dab_channel(rgb)

fig, axes = plt.subplots(1, 3, figsize=(9.2, 3.4))
axes[0].imshow(rgb)
axes[0].set_title("Input RGB (class 3+)", fontsize=9.5)
im1 = axes[1].imshow(h_map, cmap="Purples", vmin=0, vmax=float(np.percentile(h_map, 99)))
axes[1].set_title("Haematoxylin OD\n(Ruifrok & Johnston)", fontsize=9.5)
fig.colorbar(im1, ax=axes[1], fraction=0.046, pad=0.04)
im2 = axes[2].imshow(dab_map, cmap="Oranges", vmin=0, vmax=float(np.percentile(dab_map, 99)))
axes[2].set_title("DAB optical density\n(the HER2 signal)", fontsize=9.5)
fig.colorbar(im2, ax=axes[2], fraction=0.046, pad=0.04)
for ax in axes:
    ax.set_xticks([])
    ax.set_yticks([])
fig.tight_layout()
fig.savefig("stain_deconvolution.png", dpi=170)
print("wrote stain_deconvolution.png")

# ---------------------------------------------------------------------
# Figure 2: tissue detection -- Otsu-on-saturation vs. optical density
# ---------------------------------------------------------------------
rgb2 = load(faint_path)
mask_od = detect_tissue(rgb2, TissueConfig(method="od"))
mask_sat = detect_tissue(rgb2, TissueConfig(method="saturation"))
od = grey_optical_density(rgb2)

def overlay(mask: np.ndarray, rgba: tuple[float, float, float, float]) -> np.ndarray:
    """A solid-colour RGBA layer, opaque only where mask is True."""
    layer = np.zeros((*mask.shape, 4), dtype=np.float64)
    layer[mask] = rgba
    return layer


fig, axes = plt.subplots(1, 4, figsize=(11.8, 3.2))
axes[0].imshow(rgb2)
axes[0].set_title("Input RGB (class 0,\nfaint staining)", fontsize=9)
im = axes[1].imshow(od, cmap="viridis")
axes[1].set_title("Optical density", fontsize=9)
fig.colorbar(im, ax=axes[1], fraction=0.046, pad=0.04)
axes[2].imshow(rgb2)
axes[2].imshow(overlay(mask_sat, (0.85, 0.1, 0.1, 0.55)))
axes[2].set_title(
    f"Saturation-Otsu mask\n(tissue: {mask_sat.mean()*100:.1f}% of frame)", fontsize=9
)
axes[3].imshow(rgb2)
axes[3].imshow(overlay(mask_od, (0.1, 0.6, 0.2, 0.55)))
axes[3].set_title(
    f"Optical-density mask\n(tissue: {mask_od.mean()*100:.1f}% of frame)", fontsize=9
)
for ax in axes:
    ax.set_xticks([])
    ax.set_yticks([])
fig.suptitle(
    "Tissue detection on a faintly-stained patch: saturation-based Otsu under-detects,\n"
    "optical density does not",
    fontsize=9.5,
)
fig.tight_layout(rect=(0, 0, 1, 0.90))
fig.savefig("tissue_detection_comparison.png", dpi=170)
print("wrote tissue_detection_comparison.png "
      f"(saturation mask {mask_sat.mean()*100:.1f}%, OD mask {mask_od.mean()*100:.1f}%)")
