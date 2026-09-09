"""Tests for loss computation.

Losses are tested against cases whose answer is known by construction -- a
perfect prediction, a maximally wrong one, an absent class -- rather than
against recorded numbers. A regression test that only pins today's output
cannot tell a correct change from a broken one.
"""

from __future__ import annotations

import pytest
import torch

from training.config import LossConfig
from training.losses import (
    SegmentationLoss,
    focal_loss,
    inverse_frequency_weights,
    soft_dice_loss,
)

NUM_CLASSES = 5


def confident_logits(targets: torch.Tensor, magnitude: float = 20.0) -> torch.Tensor:
    """Logits that predict `targets` with near-certainty."""
    one_hot = torch.nn.functional.one_hot(targets, NUM_CLASSES)
    return one_hot.permute(0, 3, 1, 2).float() * magnitude


def test_dice_is_near_zero_for_a_perfect_prediction():
    targets = torch.randint(0, NUM_CLASSES, (2, 8, 8))
    loss = soft_dice_loss(confident_logits(targets), targets, NUM_CLASSES)
    assert loss.item() < 1e-3


def test_dice_is_near_one_for_a_completely_wrong_prediction():
    targets = torch.zeros((1, 8, 8), dtype=torch.long)
    wrong = torch.full((1, 8, 8), 4, dtype=torch.long)
    loss = soft_dice_loss(confident_logits(wrong), targets, NUM_CLASSES, smooth=0.0)
    assert loss.item() > 0.99


def test_dice_ignores_classes_absent_from_the_target():
    """A 0-score patch has no strong-staining pixels.

    Predicting none of them correctly must not be scored as a failure on that
    class, and must not be scored as a free success either -- the class is
    simply excluded, so the loss equals that of a two-class problem.
    """
    targets = torch.zeros((1, 4, 4), dtype=torch.long)
    targets[:, :2] = 1

    perfect = soft_dice_loss(confident_logits(targets), targets, NUM_CLASSES)
    assert perfect.item() < 1e-3

    # Now with only two classes defined at all: same answer, proving the
    # absent classes contributed nothing to the mean.
    two_class = soft_dice_loss(confident_logits(targets)[:, :2], targets, 2)
    assert perfect.item() == pytest.approx(two_class.item(), abs=1e-5)


def test_dice_ignores_masked_pixels():
    """Pixels marked ignore_index must not affect the loss at all."""
    targets = torch.zeros((1, 4, 4), dtype=torch.long)
    targets[:, 2:] = 1
    logits = confident_logits(targets)

    baseline = soft_dice_loss(logits, targets, NUM_CLASSES)

    masked = targets.clone()
    masked[:, :, 0] = -100
    # Make the prediction wrong exactly where it is ignored.
    corrupted = logits.clone()
    corrupted[:, :, :, 0] = 0.0
    corrupted[:, 4, :, 0] = 20.0

    assert soft_dice_loss(corrupted, masked, NUM_CLASSES).item() == pytest.approx(
        baseline.item(), abs=1e-4
    )


def test_dice_rejects_mismatched_shapes():
    logits = torch.zeros((1, NUM_CLASSES, 8, 8))
    with pytest.raises(ValueError, match="does not match"):
        soft_dice_loss(logits, torch.zeros((1, 4, 4), dtype=torch.long), NUM_CLASSES)


def test_total_loss_is_the_configured_weighted_sum():
    config = LossConfig(cross_entropy_weight=1.0, dice_weight=0.5)
    criterion = SegmentationLoss(config, NUM_CLASSES)

    targets = torch.randint(0, NUM_CLASSES, (2, 8, 8))
    logits = torch.randn(2, NUM_CLASSES, 8, 8)
    out = criterion(logits, targets)

    expected = 1.0 * out.cross_entropy + 0.5 * out.dice
    assert out.total.item() == pytest.approx(expected.item(), rel=1e-6)


def test_dice_term_is_skipped_when_its_weight_is_zero():
    criterion = SegmentationLoss(LossConfig(dice_weight=0.0), NUM_CLASSES)
    out = criterion(torch.randn(1, NUM_CLASSES, 8, 8), torch.zeros((1, 8, 8), dtype=torch.long))
    assert out.dice.item() == 0.0
    assert out.total.item() == pytest.approx(out.cross_entropy.item())


def test_loss_is_lower_for_a_better_prediction():
    criterion = SegmentationLoss(LossConfig(), NUM_CLASSES)
    targets = torch.randint(0, NUM_CLASSES, (2, 8, 8))

    good = criterion(confident_logits(targets), targets).total
    bad = criterion(confident_logits((targets + 1) % NUM_CLASSES), targets).total
    assert good.item() < bad.item()


def test_loss_produces_finite_gradients():
    criterion = SegmentationLoss(LossConfig(), NUM_CLASSES)
    logits = torch.randn(2, NUM_CLASSES, 8, 8, requires_grad=True)
    criterion(logits, torch.randint(0, NUM_CLASSES, (2, 8, 8))).total.backward()

    assert logits.grad is not None
    assert torch.isfinite(logits.grad).all()
    assert logits.grad.abs().sum() > 0


def test_class_weights_must_match_the_class_count():
    with pytest.raises(ValueError, match="class_weights"):
        SegmentationLoss(LossConfig(class_weights=[1.0, 1.0]), NUM_CLASSES)


def test_class_weights_raise_the_cost_of_erring_on_a_weighted_class():
    targets = torch.zeros((1, 4, 4), dtype=torch.long)
    targets[:, :, 0] = 4  # a few pixels of the rare class
    wrong = confident_logits(torch.zeros((1, 4, 4), dtype=torch.long))

    plain = SegmentationLoss(LossConfig(dice_weight=0.0), NUM_CLASSES)
    weighted = SegmentationLoss(
        LossConfig(dice_weight=0.0, class_weights=[1.0, 1.0, 1.0, 1.0, 10.0]),
        NUM_CLASSES,
    )
    assert weighted(wrong, targets).total.item() > plain(wrong, targets).total.item()


def test_inverse_frequency_weights_favour_the_rare_class():
    weights = inverse_frequency_weights({0: 900, 1: 90, 2: 9, 3: 1, 4: 0}, NUM_CLASSES)
    assert len(weights) == NUM_CLASSES
    assert weights[0] < weights[1] < weights[2] < weights[3] <= weights[4]


def test_focal_loss_is_near_zero_for_a_confident_correct_prediction():
    targets = torch.randint(0, NUM_CLASSES, (2, 8, 8))
    loss = focal_loss(confident_logits(targets), targets, gamma=2.0)
    assert loss.item() < 1e-3


def test_focal_loss_downweights_easy_pixels_relative_to_plain_cross_entropy():
    """The property focal loss exists for: at a fixed, middling confidence,
    its value is strictly smaller than plain cross-entropy's, and the gap
    grows with gamma -- gamma=0 must recover cross-entropy exactly."""
    targets = torch.zeros((1, 4, 4), dtype=torch.long)
    # Confident-but-not-certain logits, so p_t is neither ~0 nor ~1 -- the
    # regime where the modulating factor actually has room to act.
    logits = confident_logits(targets, magnitude=2.0)

    ce = torch.nn.functional.cross_entropy(logits, targets)
    focal_g0 = focal_loss(logits, targets, gamma=0.0)
    focal_g2 = focal_loss(logits, targets, gamma=2.0)
    focal_g5 = focal_loss(logits, targets, gamma=5.0)

    assert focal_g0.item() == pytest.approx(ce.item(), rel=1e-5)
    assert focal_g2.item() < focal_g0.item()
    assert focal_g5.item() < focal_g2.item()


def test_focal_loss_ignores_masked_pixels():
    targets = torch.zeros((1, 4, 4), dtype=torch.long)
    logits = confident_logits(targets, magnitude=2.0)
    baseline = focal_loss(logits, targets, gamma=2.0)

    masked = targets.clone()
    masked[:, :, 0] = -100
    corrupted = logits.clone()
    corrupted[:, :, :, 0] = 0.0
    corrupted[:, 4, :, 0] = 20.0  # wildly wrong exactly where it is ignored

    assert focal_loss(corrupted, masked, gamma=2.0).item() == pytest.approx(
        baseline.item(), abs=1e-4
    )


def test_focal_loss_rejects_wrong_logits_shape():
    with pytest.raises(ValueError, match="NxCxHxW"):
        focal_loss(torch.randn(1, 8, 8), torch.zeros((1, 8, 8), dtype=torch.long))


def test_focal_term_is_skipped_when_its_weight_is_zero():
    criterion = SegmentationLoss(LossConfig(focal_weight=0.0), NUM_CLASSES)
    out = criterion(torch.randn(1, NUM_CLASSES, 8, 8), torch.zeros((1, 8, 8), dtype=torch.long))
    assert out.focal.item() == 0.0


def test_focal_term_contributes_to_the_total_when_its_weight_is_positive():
    config = LossConfig(cross_entropy_weight=1.0, dice_weight=0.0, focal_weight=1.0)
    criterion = SegmentationLoss(config, NUM_CLASSES)
    targets = torch.randint(0, NUM_CLASSES, (2, 8, 8))
    logits = torch.randn(2, NUM_CLASSES, 8, 8)

    out = criterion(logits, targets)
    assert out.focal.item() > 0.0
    expected = 1.0 * out.cross_entropy + 1.0 * out.focal
    assert out.total.item() == pytest.approx(expected.item(), rel=1e-6)


def test_an_unresolved_auto_is_refused_rather_than_ignored():
    """Silently training unweighted after asking for weights is the bad case.

    It would produce a run that looks like the weighted experiment, is not,
    and whose artifact says "auto" -- a result nobody could reproduce or
    disprove.
    """
    with pytest.raises(ValueError, match="resolve_class_weights"):
        SegmentationLoss(LossConfig(class_weights="auto"), NUM_CLASSES)
