"""Tests for the architecture dispatcher shared by training and Phase 4 scripts.

Only "unet" exists (SegFormer was removed after Phase 5's comparison -- see
PHASE5.md), but the dispatcher itself stays, so this tests the dispatch
mechanism, not "there are two architectures to choose between."
"""

from __future__ import annotations

import numpy as np
import pytest

from models import prepare_pixel_array, select_architecture
from models.unet_seg import build_model as unet_build
from models.unet_seg import normalize_batch as unet_normalize


def test_select_architecture_returns_unet_symbols():
    build, normalize = select_architecture("unet")
    assert build is unet_build
    assert normalize is unet_normalize


def test_select_architecture_rejects_unknown_names():
    with pytest.raises(ValueError, match="Unknown model.architecture"):
        select_architecture("resnet50")


def test_select_architecture_names_why_segformer_is_gone_in_its_error():
    """A stale config saying architecture: segformer must fail with an
    explanation, not a bare KeyError -- this is exactly the config a reader
    migrating an old resolved_config.yaml would have."""
    with pytest.raises(ValueError, match="SegFormer was removed"):
        select_architecture("segformer")


def test_prepare_pixel_array_passes_rgb_through_unchanged_for_3_channels():
    rgb = np.full((8, 8, 3), 100, dtype=np.uint8)
    result = prepare_pixel_array(rgb, in_channels=3)
    assert result is rgb


def test_prepare_pixel_array_appends_dab_for_4_channels():
    rgb = np.full((8, 8, 3), 100, dtype=np.uint8)
    result = prepare_pixel_array(rgb, in_channels=4)
    assert result.shape == (8, 8, 4)
    assert result.dtype == np.float32


def test_prepare_pixel_array_rejects_other_channel_counts():
    with pytest.raises(ValueError, match="Unsupported in_channels"):
        prepare_pixel_array(np.zeros((4, 4, 3), dtype=np.uint8), in_channels=5)
