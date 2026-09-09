"""Tests for the ResNet18-UNet wrapper's forward-pass contract.

Built with ``pretrained=False`` throughout, so these never touch the
network. Mirrors tests/test_model.py's structure -- same properties matter
here: correct output resolution and shape, gradients reaching the encoder,
and a normalize_batch that behaves the way the model expects.
"""

from __future__ import annotations

import pytest
import torch

from models.unet_seg import IN_CHANNELS, build_model, normalize_batch
from training.config import ModelConfig


@pytest.fixture(scope="module")
def model():
    return build_model(ModelConfig(pretrained=False), verbose=False)


def test_forward_returns_logits_at_input_resolution(model):
    pixels = torch.randn(2, IN_CHANNELS, 128, 128)
    logits = model(pixels)
    assert logits.shape == (2, 5, 128, 128)


def test_forward_handles_a_non_square_input(model):
    logits = model(torch.randn(1, IN_CHANNELS, 96, 128))
    assert logits.shape == (1, 5, 96, 128)


def test_forward_handles_a_size_not_divisible_by_the_encoders_total_stride(model):
    """ResNet18 downsamples by 32x overall across five stride-2 stages.

    130 and 100 are not multiples of 32, which exercises the up-block's
    shape-matching interpolate -- the exact bug class a U-Net-on-a-CNN-encoder
    hits if odd sizes are not handled explicitly.
    """
    logits = model(torch.randn(1, IN_CHANNELS, 130, 100))
    assert logits.shape == (1, 5, 130, 100)


def test_output_class_count_follows_the_config():
    three_class = build_model(ModelConfig(pretrained=False, num_classes=3), verbose=False)
    assert three_class(torch.randn(1, IN_CHANNELS, 64, 64)).shape[1] == 3


def test_predict_returns_class_indices_in_range(model):
    predictions = model.predict(torch.randn(2, IN_CHANNELS, 64, 64))
    assert predictions.shape == (2, 64, 64)
    assert predictions.dtype == torch.long
    assert int(predictions.min()) >= 0
    assert int(predictions.max()) < 5


def test_forward_rejects_the_wrong_channel_count(model):
    with pytest.raises(ValueError, match="Nx4xHxW"):
        model(torch.randn(1, 3, 64, 64))


def test_gradients_reach_the_encoder(model):
    """A frozen or detached encoder would train the decoder alone and look fine."""
    logits = model(torch.randn(1, IN_CHANNELS, 64, 64))
    logits.sum().backward()

    conv1 = model.model.conv1.weight
    assert conv1.grad is not None and conv1.grad.abs().sum() > 0

    layer4 = dict(model.named_parameters())["model.layer4.1.conv2.weight"]
    assert layer4.grad is not None and layer4.grad.abs().sum() > 0


def test_the_dab_channel_of_conv1_starts_from_the_mean_of_the_rgb_filters():
    """The transfer-learning trick this module's docstring describes,
    pinned as a test so a refactor cannot silently zero- or randon-init it."""
    model = build_model(ModelConfig(pretrained=False), verbose=False)
    weight = model.model.conv1.weight
    torch.testing.assert_close(weight[:, 3:4], weight[:, :3].mean(dim=1, keepdim=True))


def test_normalize_batch_rejects_a_wrong_channel_count():
    with pytest.raises(ValueError, match="Nx4xHxW"):
        normalize_batch(torch.randn(1, 3, 8, 8))


def test_normalize_batch_scales_the_dab_channel_without_imagenet_statistics():
    pixels = torch.zeros(1, IN_CHANNELS, 4, 4)
    pixels[:, 3] = 0.5
    normalized = normalize_batch(pixels)
    # RGB channels of an all-zero input map to -mean/std, same as SegFormer's
    # normalize_batch; the DAB channel is a plain scale, not standardized.
    assert normalized[0, 3].mean().item() == pytest.approx(0.5)


def test_normalize_batch_treats_0_255_and_0_1_rgb_ranges_identically():
    raw = torch.randint(0, 256, (1, IN_CHANNELS, 8, 8)).float()
    raw[:, 3] = raw[:, 3] / 255.0  # DAB is never in a 0..255 range to begin with
    scaled = raw.clone()
    scaled[:, :3] = scaled[:, :3] / 255.0
    assert torch.allclose(normalize_batch(raw), normalize_batch(scaled), atol=1e-5)
