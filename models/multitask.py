"""U-Net + HER2 score head: one network, two outputs.

Why a second head
=================
The original U-Net learns only from DAB-threshold pseudo-labels, and on both
sites it scores almost exactly what that threshold rule scores (76.0% vs
75.0% in-domain, 39.9% vs 39.6% on BCI -- docs/CROSS_SITE_STAIN_NORMALIZATION.md).
A copy of the rule cannot beat the rule. The score head learns the real
0 / 1+ / 2+ / 3+ label directly, from the same encoder, while the
segmentation decoder keeps producing the explainable intensity map the
viewer shows.

Bags of tiles
=============
A label belongs to a whole patch (or a whole BCI case), while the network sees
512 px tiles. The head pools tile features with gated attention (Ilse et al.,
ICML 2018): each tile gets a learned weight, so one strongly stained tile can
carry a 3+ case even when the other tiles show stroma. That is the "crop
missed the tumour" failure seen on BCI.

Input contract
==============
``forward`` takes raw pixels: an (T, 4, H, W) float tensor with RGB in 0..1
and DAB optical density as channel 4. The model standardizes RGB itself with
the statistics its encoder weights expect, so callers never have to know
which encoder is inside.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from .unet_seg import IN_CHANNELS, ResNetUNet, rgb_statistics

NUM_SCORES = 4
SCORE_NAMES = ("0", "1+", "2+", "3+")


class GatedAttentionPool(nn.Module):
    """Attention-weighted mean of tile embeddings within each bag."""

    def __init__(self, in_dim: int, hidden: int = 128) -> None:
        super().__init__()
        self.v = nn.Linear(in_dim, hidden)
        self.u = nn.Linear(in_dim, hidden)
        self.w = nn.Linear(hidden, 1)

    def forward(self, embeddings: torch.Tensor, bag_sizes: list[int]) -> tuple[torch.Tensor, list[torch.Tensor]]:
        scores = self.w(torch.tanh(self.v(embeddings)) * torch.sigmoid(self.u(embeddings))).squeeze(-1)
        pooled, weights = [], []
        for chunk_emb, chunk_score in zip(embeddings.split(bag_sizes), scores.split(bag_sizes)):
            a = torch.softmax(chunk_score.float(), dim=0).to(chunk_emb.dtype)
            pooled.append((a[:, None] * chunk_emb).sum(0))
            weights.append(a.detach())
        return torch.stack(pooled), weights


class HER2MultiTask(nn.Module):
    def __init__(
        self,
        encoder: str = "resnet50",
        encoder_weights: str | None = "lunit_bt",
        num_seg_classes: int = 5,
        num_scores: int = NUM_SCORES,
        dropout: float = 0.2,
        weights_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.unet = ResNetUNet(
            num_classes=num_seg_classes,
            pretrained=encoder_weights is not None,
            encoder=encoder,
            encoder_weights=encoder_weights,
            weights_dir=weights_dir,
        )
        feature_dim = self.unet.encoder_channels[-1]
        self.embed = nn.Sequential(nn.Linear(2 * feature_dim, 512), nn.ReLU(inplace=True), nn.Dropout(dropout))
        self.pool = GatedAttentionPool(512)
        self.score_head = nn.Sequential(nn.Dropout(dropout), nn.Linear(512, num_scores))
        mean, std = rgb_statistics(encoder_weights)
        self.register_buffer("rgb_mean", torch.tensor(mean).view(1, 3, 1, 1), persistent=False)
        self.register_buffer("rgb_std", torch.tensor(std).view(1, 3, 1, 1), persistent=False)
        self.config = {
            "encoder": encoder,
            "encoder_weights": encoder_weights,
            "num_seg_classes": num_seg_classes,
            "num_scores": num_scores,
            "dropout": dropout,
        }

    def standardize(self, pixels: torch.Tensor) -> torch.Tensor:
        if pixels.ndim != 4 or pixels.shape[1] != IN_CHANNELS:
            raise ValueError(f"Expected a Tx4xHxW batch, got {tuple(pixels.shape)}")
        rgb = (pixels[:, :3] - self.rgb_mean.to(pixels.dtype)) / self.rgb_std.to(pixels.dtype)
        return torch.cat([rgb, pixels[:, 3:4]], dim=1)

    def forward(self, pixels: torch.Tensor, bag_sizes: list[int], with_seg: bool = True) -> dict:
        """Tiles in, (tile segmentation logits, bag score logits, attention) out."""
        if sum(bag_sizes) != pixels.shape[0]:
            raise ValueError(f"bag_sizes sum to {sum(bag_sizes)} but there are {pixels.shape[0]} tiles")
        seg_logits, features = self.unet(self.standardize(pixels), return_features=True, with_seg=with_seg)
        tile_embedding = self.embed(torch.cat([features.mean((2, 3)), features.amax((2, 3))], dim=1))
        bag_embedding, attention = self.pool(tile_embedding, bag_sizes)
        return {"seg_logits": seg_logits, "score_logits": self.score_head(bag_embedding), "attention": attention}

    @staticmethod
    def expected_score(score_logits: torch.Tensor) -> torch.Tensor:
        probs = F.softmax(score_logits.float(), dim=-1)
        return (probs * torch.arange(probs.shape[-1], device=probs.device)).sum(-1)


def build_multitask(config: dict, weights_dir: str | None = None) -> HER2MultiTask:
    return HER2MultiTask(
        encoder=config.get("encoder", "resnet50"),
        encoder_weights=config.get("encoder_weights", "lunit_bt"),
        num_seg_classes=int(config.get("num_seg_classes", 5)),
        num_scores=int(config.get("num_scores", NUM_SCORES)),
        dropout=float(config.get("dropout", 0.2)),
        weights_dir=weights_dir,
    )
