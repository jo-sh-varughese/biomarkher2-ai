"""BioMarkHER2 model wrappers.

Phase 5's SegFormer-vs-U-Net comparison (see PHASE5.md) decided this: on
identical data, split and epochs, ResNet18-UNet beat SegFormer on every
single class -- most dramatically on moderate (2+), 0.589 IoU against
SegFormer's 0.00006 under otherwise identical conditions. SegFormer has
been removed, not archived-in-place, per that decision.

The `select_architecture`/`prepare_pixel_array` dispatch below is kept
deliberately thin rather than removed outright, even with only one
architecture registered: it cost little to add, and it is the one place a
second architecture would need to be wired back in if that ever becomes
worth doing again -- training/train.py and the Phase 4 scripts already call
through it rather than importing a model module directly, so nothing else
would need to change.
"""

import numpy as np

from .unet_seg import (
    IMAGENET_MEAN,
    IMAGENET_STD,
    IN_CHANNELS,
    UNetSegmenter,
    build_model,
    normalize_batch,
)

__all__ = [
    "IMAGENET_MEAN",
    "IMAGENET_STD",
    "IN_CHANNELS",
    "UNetSegmenter",
    "build_model",
    "normalize_batch",
    "select_architecture",
    "prepare_pixel_array",
]


def select_architecture(architecture: str):
    """Return (build_model, normalize_batch) for the named architecture.

    Only "unet" exists today -- see the module docstring. The one place
    this dispatch is written; training/train.py and both Phase 4 scripts
    (scripts/calibrate_conformal.py, scripts/evaluate_conformal.py) call
    this rather than importing a model module directly, so a future second
    architecture would only need registering here.
    """
    if architecture == "unet":
        from .unet_seg import build_model, normalize_batch

        return build_model, normalize_batch
    raise ValueError(
        f"Unknown model.architecture {architecture!r}; expected 'unet' "
        "(SegFormer was removed after Phase 5's comparison -- see PHASE5.md)."
    )


def prepare_pixel_array(rgb: np.ndarray, in_channels: int) -> np.ndarray:
    """RGB (HxWx3 uint8) -> the array shape a model of ``in_channels`` expects.

    3 channels: RGB unchanged. 4 channels: RGB with DAB optical density
    appended as a 4th channel (float32, HxWx4) -- see models/unet_seg.py's
    module docstring for why. Used at inference time, so a checkpoint's
    ``in_channels`` alone decides whether a caller needs to compute DAB,
    rather than every call site importing preprocessing.stains itself.
    """
    if in_channels == 3:
        return rgb
    if in_channels == 4:
        from preprocessing.stains import dab_channel

        dab = dab_channel(rgb).astype(np.float32)
        rgb_float = rgb.astype(np.float32)
        return np.concatenate([rgb_float, dab[..., None]], axis=-1)
    raise ValueError(f"Unsupported in_channels {in_channels!r}; expected 3 or 4.")
