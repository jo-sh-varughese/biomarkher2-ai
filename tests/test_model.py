"""Tests for the SegFormer wrapper's forward-pass contract.

Built with ``pretrained=False`` throughout, so these never touch the network
and never depend on a HuggingFace cache being warm.

The property under test is the one the wrapper exists for: logits come back at
the *input* resolution, not SegFormer's native quarter resolution. If that
regressed, the loss and the metrics would silently be computed on differently
sized tensors elsewhere in the codebase.
"""

from __future__ import annotations

import pytest
import torch

from models.segformer_seg import IMAGENET_MEAN, build_model, normalize_batch
from training.config import ModelConfig


@pytest.fixture(scope="module")
def model():
    return build_model(ModelConfig(pretrained=False), verbose=False)


def test_forward_returns_logits_at_input_resolution(model):
    pixels = torch.randn(2, 3, 128, 128)
    logits = model(pixels)
    assert logits.shape == (2, 5, 128, 128)


def test_forward_handles_a_non_square_input(model):
    logits = model(torch.randn(1, 3, 96, 128))
    assert logits.shape == (1, 5, 96, 128)


def test_output_class_count_follows_the_config():
    three_class = build_model(ModelConfig(pretrained=False, num_classes=3), verbose=False)
    assert three_class(torch.randn(1, 3, 64, 64)).shape[1] == 3


def test_predict_returns_class_indices_in_range(model):
    predictions = model.predict(torch.randn(2, 3, 64, 64))
    assert predictions.shape == (2, 64, 64)
    assert predictions.dtype == torch.long
    assert int(predictions.min()) >= 0
    assert int(predictions.max()) < 5


def test_forward_rejects_an_unbatched_image(model):
    with pytest.raises(ValueError, match="Nx3xHxW"):
        model(torch.randn(3, 64, 64))


def test_gradients_reach_the_encoder(model):
    """A frozen or detached encoder would train the head alone and look fine."""
    logits = model(torch.randn(1, 3, 64, 64))
    logits.sum().backward()

    # "model.segformer.*" is the backbone; "model.decode_head.*" is the head.
    backbone_grads = [
        p.grad for name, p in model.named_parameters()
        if name.startswith("model.segformer.") and p.grad is not None
    ]
    assert backbone_grads, "no backbone parameter received a gradient"
    assert any(g.abs().sum() > 0 for g in backbone_grads)

    # Specifically the first patch embedding -- the furthest point from the
    # loss, and the first thing to go if something upstream detaches.
    first = dict(model.named_parameters())[
        "model.segformer.stages.0.patch_embeddings.proj.weight"
    ]
    assert first.grad is not None and first.grad.abs().sum() > 0


def test_normalize_batch_maps_uint8_range_onto_imagenet_statistics():
    pixels = torch.zeros(1, 3, 4, 4)
    normalized = normalize_batch(pixels)
    # Black maps to -mean/std on every channel.
    assert normalized[0, 0].mean().item() == pytest.approx(
        -IMAGENET_MEAN[0] / 0.229, rel=1e-4
    )


def test_normalize_batch_treats_0_255_and_0_1_inputs_identically():
    raw = torch.randint(0, 256, (1, 3, 8, 8)).float()
    assert torch.allclose(normalize_batch(raw), normalize_batch(raw / 255.0), atol=1e-5)


def test_normalize_batch_rejects_a_wrong_channel_count():
    with pytest.raises(ValueError, match="Nx3xHxW"):
        normalize_batch(torch.randn(1, 1, 8, 8))
