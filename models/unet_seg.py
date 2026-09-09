"""A compact U-Net over a pretrained ResNet18 encoder, for HER2 intensity segmentation.

WHY THIS EXISTS ALONGSIDE SEGFORMER, NOT INSTEAD OF IT
========================================================
Phase 2's SegFormer run diagnosed a specific, documented failure (see
PHASE2.md, "Run 1 -- effective 20x, and the failure it exposed"): SegFormer's
decode head predicts at H/4 x W/4 and is then bilinearly upsampled, so the
thin membrane rims the label classes are actually made of were sub-pixel at
the resolution the model predicts, before ever reaching the loss. Moving to
native 40x helped, but the model still essentially never predicts the
moderate (2+) class (validation IoU 0.0001).

A U-Net decoder with skip connections is architecturally the more direct fix
for exactly this failure mode: it recovers full input resolution through the
decoder itself, using the encoder's own full-resolution early feature maps
as skip connections at every scale, rather than relying on one coarse decode
head and a single upsample to invent detail that was never predicted.

This is not a replacement for SegFormer, by design. The classical DAB
threshold baseline was never removed from this project either, for the same
reason: a new model earns its place by being measured against the old one on
the same held-out data, not by assumption. See PHASE5.md for that comparison.

FEATURE-INFORMED INPUT
========================
This model accepts 4 input channels, not 3: RGB plus the DAB optical-density
channel already computed by preprocessing/stains.py. The pseudo-label
targets this project trains on ARE a function of DAB optical density (see
training/pseudo_labels.py) -- handing the model that exact, physically
meaningful quantity as an input channel, rather than requiring it to
re-derive an approximation of DAB absorption from raw RGB through learned
convolutions, is a deliberate inductive bias for a weakly-supervised setting
with very little signal for the rarest class. The first convolution's extra
input channel is initialized from the mean of the pretrained RGB weights
(see ResNetUNet.__init__), a standard transfer-learning trick for adding a
channel without discarding ImageNet pretraining on the other three.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision.models import ResNet18_Weights, resnet18

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)

# The DAB channel is optical density, not a pixel intensity -- it has its own
# scale (see preprocessing/stains.py's dab_od_* thresholds, which top out
# around 0.8-1.0 for strong staining). Dividing by this constant maps the
# range real slides occupy onto roughly [0, 1.5], comparable in scale to the
# standardized RGB channels beside it, without depending on any one batch's
# own statistics the way batch normalization would.
DAB_NORMALIZE_SCALE = 1.0

IN_CHANNELS = 4


def normalize_batch(pixels: torch.Tensor) -> torch.Tensor:
    """Normalize a 4-channel (RGB + DAB) batch for the U-Net encoder.

    The first three channels are standardized with ImageNet statistics (they
    feed a pretrained ResNet18 stem); the fourth is DAB optical density,
    already a bounded, physically meaningful quantity, scaled rather than
    standardized -- see DAB_NORMALIZE_SCALE.
    """
    if pixels.ndim != 4 or pixels.shape[1] != IN_CHANNELS:
        raise ValueError(f"Expected an Nx4xHxW batch, got {tuple(pixels.shape)}")
    rgb = pixels[:, :3]
    dab = pixels[:, 3:4]
    if rgb.max() > 1.5:  # still in 0..255
        rgb = rgb / 255.0
    mean = torch.tensor(IMAGENET_MEAN, dtype=rgb.dtype, device=rgb.device).view(1, 3, 1, 1)
    std = torch.tensor(IMAGENET_STD, dtype=rgb.dtype, device=rgb.device).view(1, 3, 1, 1)
    rgb = (rgb - mean) / std
    dab = dab / DAB_NORMALIZE_SCALE
    return torch.cat([rgb, dab], dim=1)


class _ConvBlock(nn.Module):
    """Two 3x3 convs (+BN+ReLU) -- the standard U-Net decoder unit."""

    def __init__(self, in_channels: int, out_channels: int) -> None:
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_channels, out_channels, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.block(x)


class _UpBlock(nn.Module):
    """Upsample, concatenate the matching encoder skip, then a conv block."""

    def __init__(self, in_channels: int, skip_channels: int, out_channels: int) -> None:
        super().__init__()
        self.conv = _ConvBlock(in_channels + skip_channels, out_channels)

    def forward(self, x: torch.Tensor, skip: torch.Tensor | None) -> torch.Tensor:
        x = F.interpolate(x, scale_factor=2, mode="bilinear", align_corners=False)
        if skip is not None:
            if x.shape[-2:] != skip.shape[-2:]:
                # Five stride-2 stages can round odd input sizes differently
                # on the way down; matching the skip's size is the one place
                # that must be exact, so an off-by-one here is handled, not
                # left to fail a concatenation shape check three lines later.
                x = F.interpolate(x, size=skip.shape[-2:], mode="bilinear", align_corners=False)
            x = torch.cat([x, skip], dim=1)
        return self.conv(x)


class ResNetUNet(nn.Module):
    """U-Net decoder over a torchvision ResNet18 encoder, 4-channel input.

    STOPPING AT STRIDE 2, NOT STRIDE 1
    ====================================
    A first version of this decoder ran one more stage, with a learned
    convolution block at the input's own full resolution (stride 1) before
    the classifier. Measured, not assumed: on this CPU-only machine, that
    single stage cost roughly as much as the rest of the decoder combined --
    convolution cost scales with the number of spatial positions, and going
    from stride 2 to stride 1 quadruples that number. A smoke run (8 fit / 4
    val patches, 1 epoch) took 170s with it; SegFormer's own comparable
    smoke-scale figures (PHASE2.md) are close to an order of magnitude
    faster per image. That is not a viable trade on this hardware for the
    resolution gained, so the decoder stops at stride 2 -- still twice the
    resolution of SegFormer's stride-4 decode head, which is the specific,
    documented mechanism (PHASE2.md) this model exists to improve on, at a
    cost this machine can actually afford. See PHASE5.md for the measured
    comparison this tradeoff was decided from.
    """

    def __init__(self, num_classes: int, pretrained: bool = True) -> None:
        super().__init__()
        weights = ResNet18_Weights.IMAGENET1K_V1 if pretrained else None
        backbone = resnet18(weights=weights)

        original_conv1 = backbone.conv1
        self.conv1 = nn.Conv2d(IN_CHANNELS, 64, kernel_size=7, stride=2, padding=3, bias=False)
        with torch.no_grad():
            self.conv1.weight[:, :3] = original_conv1.weight
            # The fourth (DAB) channel starts as the mean of the pretrained
            # RGB filters, not zeros or a random init -- zeros would make the
            # new channel contribute nothing at the start of training, and a
            # random init would discard the one piece of pretrained
            # structure (edge/blob detectors) a physically related channel
            # can plausibly reuse.
            self.conv1.weight[:, 3:4] = original_conv1.weight.mean(dim=1, keepdim=True)

        self.bn1 = backbone.bn1
        self.relu = backbone.relu
        self.maxpool = backbone.maxpool
        self.layer1 = backbone.layer1
        self.layer2 = backbone.layer2
        self.layer3 = backbone.layer3
        self.layer4 = backbone.layer4

        self.up4 = _UpBlock(512, 256, 256)
        self.up3 = _UpBlock(256, 128, 128)
        self.up2 = _UpBlock(128, 64, 64)
        self.up1 = _UpBlock(64, 64, 64)
        self.classifier = nn.Conv2d(64, num_classes, kernel_size=1)
        # Deliberately no learned stage at the input's own full resolution --
        # see the class docstring's "STOPPING AT STRIDE 2" note. The final
        # step from stride 2 to stride 1 is a plain, non-learned upsample of
        # the LOGITS -- SegFormer's own decode head (removed, see PHASE5.md)
        # reached input resolution the same way, by bilinear upsample of
        # its own lower-resolution logits.

    def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
        if pixel_values.ndim != 4 or pixel_values.shape[1] != IN_CHANNELS:
            raise ValueError(
                f"Expected an Nx4xHxW batch, got {tuple(pixel_values.shape)}"
            )
        height, width = pixel_values.shape[-2:]

        s0 = self.relu(self.bn1(self.conv1(pixel_values)))  # stride 2,  64ch
        s1 = self.layer1(self.maxpool(s0))                  # stride 4,  64ch
        s2 = self.layer2(s1)                                # stride 8,  128ch
        s3 = self.layer3(s2)                                # stride 16, 256ch
        s4 = self.layer4(s3)                                # stride 32, 512ch

        x = self.up4(s4, s3)   # stride 16
        x = self.up3(x, s2)    # stride 8
        x = self.up2(x, s1)    # stride 4
        x = self.up1(x, s0)    # stride 2 -- stops here, see class docstring
        logits = self.classifier(x)

        if logits.shape[-2:] != (height, width):
            logits = F.interpolate(
                logits, size=(height, width), mode="bilinear", align_corners=False
            )
        return logits


class UNetSegmenter(nn.Module):
    """Dense intensity-class segmentation, logits at input resolution.

    Deliberately kept to the same narrow public contract SegFormer's now-
    removed wrapper had -- forward/predict/trainable_parameters -- so callers
    that only need "a segmentation model" (the conformal-prediction and
    evaluation code in :mod:`evaluation`, in particular) never had to change
    when the architecture did.
    """

    def __init__(self, model: ResNetUNet, num_classes: int) -> None:
        super().__init__()
        self.model = model
        self.num_classes = num_classes

    def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
        return self.model(pixel_values)

    @torch.no_grad()
    def predict(self, pixel_values: torch.Tensor) -> torch.Tensor:
        self.eval()
        return self.forward(pixel_values).argmax(dim=1)

    def trainable_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)


def build_model(config, verbose: bool = True) -> UNetSegmenter:
    """Construct the U-Net from a :class:`training.config.ModelConfig`.

    With ``config.pretrained`` False this builds an untrained ResNet18 (no
    network access) -- SegFormer's own build_model offered the same test-only
    path, for the same reason: a forward-pass test must never depend on a
    download.
    """
    backbone = ResNetUNet(num_classes=config.num_classes, pretrained=config.pretrained)
    if verbose:
        state = "ImageNet-pretrained" if config.pretrained else "randomly initialized"
        print(
            f"Built ResNet18-UNet ({state} encoder), 4-channel (RGB+DAB) input, "
            f"{config.num_classes} output classes."
        )
    return UNetSegmenter(backbone, config.num_classes)
