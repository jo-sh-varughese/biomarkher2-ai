"""SegFormer wrapped so the rest of the codebase never sees HuggingFace.

Two things this wrapper exists to handle, both of which are easy to get
silently wrong:

**The logits come out at quarter resolution.** SegFormer's decode head
predicts at H/4 x W/4 and the reference implementation upsamples afterwards.
If that upsample is left to the caller it eventually gets forgotten somewhere
-- typically in the metrics path but not the loss path, or the other way
round -- and the two then disagree about what a pixel is. :meth:`forward`
therefore always returns logits at the input resolution, and nothing outside
this module ever handles the quarter-resolution tensor.

**The pretrained head is the wrong shape.** ``segformer-b0-finetuned-ade``
carries a 150-class ADE20K head; we need 5. The encoder weights are what we
want to keep, so the head is re-initialised and the size mismatch is expected
rather than an error -- but it is announced, because "loaded pretrained
weights" quietly meaning "except the entire output layer" is worth seeing in
a log.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from transformers import SegformerConfig, SegformerForSemanticSegmentation

# The statistics the pretrained encoder was trained under. Using anything else
# shifts every activation and throws away much of the value of pretraining.
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def normalize_batch(pixels: torch.Tensor) -> torch.Tensor:
    """Scale uint8-valued NCHW pixels to the encoder's expected distribution."""
    if pixels.ndim != 4 or pixels.shape[1] != 3:
        raise ValueError(f"Expected an Nx3xHxW batch, got {tuple(pixels.shape)}")
    x = pixels.float()
    if x.max() > 1.5:  # still in 0..255
        x = x / 255.0
    mean = torch.tensor(IMAGENET_MEAN, dtype=x.dtype, device=x.device).view(1, 3, 1, 1)
    std = torch.tensor(IMAGENET_STD, dtype=x.dtype, device=x.device).view(1, 3, 1, 1)
    return (x - mean) / std


class SegformerSegmenter(nn.Module):
    """Dense intensity-class segmentation, logits at input resolution."""

    def __init__(self, model: SegformerForSemanticSegmentation, num_classes: int) -> None:
        super().__init__()
        self.model = model
        self.num_classes = num_classes

    def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
        """Return NxCxHxW logits, H and W matching ``pixel_values``."""
        if pixel_values.ndim != 4:
            raise ValueError(
                f"Expected an Nx3xHxW batch, got shape {tuple(pixel_values.shape)}"
            )
        height, width = pixel_values.shape[-2:]
        logits = self.model(pixel_values=pixel_values).logits
        if logits.shape[-2:] != (height, width):
            # Bilinear, matching the reference SegFormer implementation.
            # align_corners=False keeps the sampling grid consistent with how
            # the labels were subsampled.
            logits = F.interpolate(
                logits, size=(height, width), mode="bilinear", align_corners=False
            )
        return logits

    @torch.no_grad()
    def predict(self, pixel_values: torch.Tensor) -> torch.Tensor:
        """Return NxHxW predicted class indices."""
        self.eval()
        return self.forward(pixel_values).argmax(dim=1)

    def trainable_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)


def build_model(config, verbose: bool = True) -> SegformerSegmenter:
    """Construct the segmenter from a :class:`training.config.ModelConfig`.

    With ``config.pretrained`` False the model is built from architecture
    alone and no network access occurs -- that is the path the tests take, so
    a forward-pass test never depends on a download.
    """
    if config.pretrained:
        model = SegformerForSemanticSegmentation.from_pretrained(
            config.checkpoint,
            num_labels=config.num_classes,
            ignore_mismatched_sizes=True,
        )
        if verbose:
            print(
                f"Loaded encoder weights from {config.checkpoint}; the decode head "
                f"was re-initialised for {config.num_classes} classes."
            )
    else:
        hf_config = SegformerConfig.from_pretrained(config.checkpoint) \
            if _is_local(config.checkpoint) else SegformerConfig()
        hf_config.num_labels = config.num_classes
        model = SegformerForSemanticSegmentation(hf_config)
        if verbose:
            print("Built SegFormer from architecture only (no pretrained weights).")

    return SegformerSegmenter(model, config.num_classes)


def _is_local(checkpoint: str) -> bool:
    from pathlib import Path

    return Path(checkpoint).is_dir()
