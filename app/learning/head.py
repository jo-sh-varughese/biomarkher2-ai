"""The learnable part of the pre-score model, and how it is trained and judged.

The model is encoder -> tile embedding (T x 512) -> gated attention pooling
-> score head. Learning updates only the pooling and the score head (~66k
parameters) on stored, frozen tile embeddings: fast on a CPU, and too small
to memorise individual cases. The encoder is never changed here; retraining
it needs the GPU workflow (docs/V2_TRAINING_PLAN.md).

Training data for an update:
* bag labels -- confirmed (signed) review scores of local cases;
* tile labels -- region annotations: tiles inside an annotated region get the
  region's score (the score head applied to a tile embedding is the same
  head that produces the per-region grades the portal shows);
* replay -- training-site cases mixed 1:1 into every epoch, so the meaning of
  each grade is kept (no catastrophic forgetting);
* an anchor penalty pulling the weights towards the version being updated.
"""

from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass, field

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class Case:
    emb: np.ndarray                    # (T, 512) tile embeddings
    label: int | None = None           # confirmed score 0..3 (None: unlabelled)
    tile_labels: dict = field(default_factory=dict)  # tile index -> score 0..3 (from annotations)
    case_id: str = ""


class Head(nn.Module):
    """Attention pooling + score head, initialised from a trained HER2MultiTask."""

    def __init__(self, pool: nn.Module, score_head: nn.Module) -> None:
        super().__init__()
        self.pool = copy.deepcopy(pool)
        self.score_head = copy.deepcopy(score_head)

    @classmethod
    def from_model(cls, model) -> "Head":
        return cls(model.pool, model.score_head)

    def bag_logits(self, embs: list[torch.Tensor]) -> torch.Tensor:
        sizes = [e.shape[0] for e in embs]
        bag, _ = self.pool(torch.cat(embs), sizes)
        return self.score_head(bag)

    def tile_logits(self, emb: torch.Tensor) -> torch.Tensor:
        return self.score_head(emb)

    def state(self) -> dict:
        return {"pool": self.pool.state_dict(), "score_head": self.score_head.state_dict()}

    def load(self, state: dict) -> "Head":
        self.pool.load_state_dict(state["pool"])
        self.score_head.load_state_dict(state["score_head"])
        return self


def _t(a: np.ndarray) -> torch.Tensor:
    return torch.from_numpy(np.asarray(a, dtype=np.float32))


@torch.no_grad()
def predict(head: Head, cases: list[Case], batch: int = 64) -> np.ndarray:
    head.eval()
    out = []
    for i in range(0, len(cases), batch):
        out.append(F.softmax(head.bag_logits([_t(c.emb) for c in cases[i:i + batch]]).float(), -1).numpy())
    return np.concatenate(out) if out else np.zeros((0, 4))


def metrics(head: Head, cases: list[Case]) -> dict:
    from evaluation.score_metrics import score_metrics

    labelled = [c for c in cases if c.label is not None]
    if not labelled:
        return {"n": 0}
    probs = predict(head, labelled)
    y = [c.label for c in labelled]
    pred = probs.argmax(1).tolist()
    m = score_metrics(y, pred)
    big = float(np.mean([abs(a - b) >= 2 for a, b in zip(y, pred)]))
    return {"n": len(y), "accuracy": round(float(m["accuracy"]), 4), "qwk": round(float(m["qwk"]), 4),
            "balanced_accuracy": round(float(m.get("balanced_accuracy", 0.0)), 4), "big_error_rate": round(big, 4)}


def train(start: Head, local: list[Case], replay: list[Case], *, epochs: int = 40, lr: float = 1e-3,
          anchor: float = 1e-2, tile_weight: float = 0.5, batch: int = 16, seed: int = 0) -> Head:
    """A new head trained from ``start`` on local labelled cases (+ annotated tiles) with replay."""
    rng = random.Random(seed)
    torch.manual_seed(seed)
    head = copy.deepcopy(start)
    ref = {k: v.detach().clone() for k, v in head.named_parameters()}
    bags = [c for c in local if c.label is not None]
    tiles = [(c, i, y) for c in local for i, y in c.tile_labels.items()]
    if not bags and not tiles:
        return head
    counts = np.bincount([c.label for c in bags], minlength=4) if bags else np.ones(4)
    class_w = torch.tensor([len(bags) / (4 * max(1, n)) if n else 0.0 for n in counts], dtype=torch.float32)
    opt = torch.optim.AdamW(head.parameters(), lr=lr, weight_decay=1e-4)
    head.train()
    steps = max(1, math.ceil(max(len(bags), 1) / batch))
    for _ in range(epochs):
        order = bags[:]
        rng.shuffle(order)
        for s in range(steps):
            chunk = order[s * batch:(s + 1) * batch]
            rep = rng.sample(replay, min(len(replay), max(len(chunk), batch // 2))) if replay else []
            loss = torch.zeros(())
            if chunk:
                logits = head.bag_logits([_t(c.emb) for c in chunk])
                loss = loss + F.cross_entropy(logits, torch.tensor([c.label for c in chunk]), weight=class_w)
            if rep:
                loss = loss + F.cross_entropy(head.bag_logits([_t(c.emb) for c in rep]), torch.tensor([c.label for c in rep]))
            if tiles:
                pick = rng.sample(tiles, min(len(tiles), 64))
                emb = torch.stack([_t(c.emb[i]) for c, i, _ in pick])
                loss = loss + tile_weight * F.cross_entropy(head.tile_logits(emb), torch.tensor([y for _, _, y in pick]))
            loss = loss + anchor * sum(((p - ref[k]) ** 2).sum() for k, p in head.named_parameters())
            opt.zero_grad()
            loss.backward()
            opt.step()
    head.eval()
    return head


def cross_validate(start: Head, local: list[Case], replay: list[Case], folds: int = 5, seed: int = 0, **kw) -> dict:
    """Out-of-fold predictions: the current head vs a head trained without each fold."""
    labelled = [c for c in local if c.label is not None]
    if len(labelled) < folds * 2:
        return {"n": len(labelled), "enough": False}
    rng = random.Random(seed)
    idx = list(range(len(labelled)))
    rng.shuffle(idx)
    fold_of = {i: k % folds for k, i in enumerate(idx)}
    cur_pred, new_pred, y = [], [], []
    for f in range(folds):
        test = [labelled[i] for i in idx if fold_of[i] == f]
        train_cases = [labelled[i] for i in idx if fold_of[i] != f] + [c for c in local if c.label is None and c.tile_labels]
        cand = train(start, train_cases, replay, seed=seed + f, **kw)
        cur_pred += predict(start, test).argmax(1).tolist()
        new_pred += predict(cand, test).argmax(1).tolist()
        y += [c.label for c in test]
    from evaluation.score_metrics import score_metrics

    def summary(pred):
        m = score_metrics(y, pred)
        return {"accuracy": round(float(m["accuracy"]), 4), "qwk": round(float(m["qwk"]), 4),
                "big_error_rate": round(float(np.mean([abs(a - b) >= 2 for a, b in zip(y, pred)])), 4)}

    return {"n": len(y), "enough": True, "current": summary(cur_pred), "candidate": summary(new_pred)}
