"""AI HER2 pre-score with explanations, from the multi-task model (models/multitask.py).

What the pathologist gets, and how each piece is computed:

* **Pre-score and probabilities** -- the score head's softmax over 0/1+/2+/3+
  for the whole field (all tiles pooled by gated attention).
* **Regional pre-scores** -- the same score head applied to every 512 px tile
  on its own, so a field that is 3+ in one corner and 0 elsewhere shows it
  (heterogeneity) instead of averaging it away.
* **Attention** -- how much each tile contributed to the field pre-score.
* **Evidence heatmap** -- Grad-CAM (Selvaraju et al., ICCV 2017) of the
  predicted grade on the encoder's last feature map: which pixels pushed the
  model toward that grade.
* **Uncertainty** -- top probability, margin to the runner-up, and whether the
  two most likely grades are neighbours (a borderline case) or far apart (a
  confused one).

The pre-score is a suggestion for the pathologist. Whether it may be shown at
all is decided by the site safety gate (evaluation/safety_gate.py), not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from models.multitask import SCORE_NAMES
from training import gpu_ops

TILE = 512
GRADE_COLORS = {"0": (110, 130, 160), "1+": (232, 196, 60), "2+": (236, 128, 40), "3+": (200, 30, 40)}


@dataclass
class PrescoreResult:
    probabilities: dict
    category: str
    confidence: float
    margin: float
    runner_up: str
    borderline: bool
    tiles: list = field(default_factory=list)
    grid: tuple = (0, 0)
    heterogeneity: dict = field(default_factory=dict)
    evidence_map: np.ndarray | None = None
    model: dict = field(default_factory=dict)

    def public(self) -> dict:
        return {"category": self.category, "probabilities": self.probabilities,
                "confidence": round(self.confidence, 3), "margin_to_runner_up": round(self.margin, 3),
                "runner_up": self.runner_up, "borderline": self.borderline, "regions": self.tiles,
                "grid": list(self.grid), "heterogeneity": self.heterogeneity, "model": self.model}


GRADE_NAMES = ("0", "1+", "2+", "3+")


def prediction_set(probabilities: dict, run_dir: Path, site: str | None, alpha: float = 0.1) -> dict:
    """Conformal prediction set for one field's pre-score (scripts/calibrate_prescore_sets.py).

    Shown only when the calibration was made for THIS site: a set calibrated at
    one hospital lost its guarantee at another (95% promised, 82% delivered at
    BCI; PHASE4.md, Objective 2), so a mismatched calibration is reported as
    unavailable rather than shown with a coverage it does not have.
    """
    import json

    path = Path(run_dir) / "prescore_sets.json"
    if not path.is_file():
        return {"available": False, "reason": "No conformal calibration for this model."}
    cal = json.loads(path.read_text(encoding="utf-8"))
    if site and cal.get("site") != site:
        return {"available": False,
                "reason": f"Calibrated for {cal.get('site')}, not for this site; calibrate with local cases first."}
    q = float(cal["thresholds"][str(alpha)])
    grades = [g for g in GRADE_NAMES if 1.0 - float(probabilities.get(g, 0.0)) <= q]
    return {"available": True, "coverage": round(1 - alpha, 2), "grades": grades,
            "calibrated_for": cal.get("site"), "n_cases": cal.get("n_cases")}


class PrescoreEngine:
    def __init__(self, checkpoint: str | Path, device: str = "cpu") -> None:
        from training.v2_engine import load_model

        self.checkpoint = Path(checkpoint)
        self.device = torch.device(device)
        self.model = load_model(self.checkpoint, self.device).float()
        ck = torch.load(self.checkpoint, map_location="cpu", weights_only=False)
        state = ck.get("state", {})
        self.info = {"checkpoint": str(self.checkpoint), "epoch": state.get("epoch"),
                     "encoder": self.model.config.get("encoder"), "trained_on": ck.get("config", {}).get("data", {}).get("train_sites")}

    def _tiles(self, rgb: np.ndarray):
        h, w = rgb.shape[:2]
        rows, cols = max(1, -(-h // TILE)), max(1, -(-w // TILE))
        canvas = np.full((rows * TILE, cols * TILE, 3), 255, dtype=np.uint8)
        canvas[:h, :w] = rgb
        x = torch.from_numpy(canvas).permute(2, 0, 1)[None].float().div(255.0)
        return gpu_ops.to_tiles(x, TILE), rows, cols, canvas

    def run(self, rgb: np.ndarray, tissue: np.ndarray | None = None) -> PrescoreResult:
        tiles, rows, cols, canvas = self._tiles(rgb)
        tissue_frac = np.ones(rows * cols)
        if tissue is not None:
            t = np.zeros(canvas.shape[:2], dtype=bool)
            t[: tissue.shape[0], : tissue.shape[1]] = tissue
            tissue_frac = np.array([t[r * TILE:(r + 1) * TILE, c * TILE:(c + 1) * TILE].mean() for r in range(rows) for c in range(cols)])
        m = self.model
        pixels = gpu_ops.model_input(tiles).to(self.device)
        with torch.enable_grad():
            _, feats = m.unet(m.standardize(pixels), return_features=True, with_seg=False)
            tile_emb = m.embed(torch.cat([feats.mean((2, 3)), feats.amax((2, 3))], 1))
            bag, attention = m.pool(tile_emb, [tile_emb.shape[0]])
            logits = m.score_head(bag)[0]
            pred = int(logits.argmax())
            grad = torch.autograd.grad(logits[pred], feats)[0]
        with torch.no_grad():
            probs = F.softmax(logits.float(), -1).numpy()
            tile_probs = F.softmax(m.score_head(tile_emb).float(), -1).numpy()
            cam = F.relu((grad.mean((2, 3), keepdim=True) * feats).sum(1, keepdim=True))
            cam = F.interpolate(cam, size=(TILE, TILE), mode="bilinear", align_corners=False)[:, 0].numpy()
        heat = np.zeros((rows * TILE, cols * TILE), dtype=np.float32)
        for i in range(rows * cols):
            r, c = divmod(i, cols)
            heat[r * TILE:(r + 1) * TILE, c * TILE:(c + 1) * TILE] = cam[i]
        heat = heat[: rgb.shape[0], : rgb.shape[1]]
        heat = heat / max(1e-6, float(np.percentile(heat, 99.5)))
        order = np.argsort(-probs)
        att = attention[0].numpy()
        regions = []
        for i in range(rows * cols):
            r, c = divmod(i, cols)
            regions.append({"row": r, "col": c, "category": SCORE_NAMES[int(tile_probs[i].argmax())],
                            "probabilities": {SCORE_NAMES[k]: round(float(tile_probs[i][k]), 3) for k in range(4)},
                            "attention": round(float(att[i]), 4), "tissue_fraction": round(float(tissue_frac[i]), 3)})
        tissue_regions = [g for g in regions if g["tissue_fraction"] >= 0.15] or regions
        share = {s: round(sum(g["category"] == s for g in tissue_regions) / len(tissue_regions), 3) for s in SCORE_NAMES}
        spread = max(SCORE_NAMES.index(g["category"]) for g in tissue_regions) - min(SCORE_NAMES.index(g["category"]) for g in tissue_regions)
        heterogeneous = spread >= 2 and len(tissue_regions) >= 2
        return PrescoreResult(
            probabilities={SCORE_NAMES[k]: round(float(probs[k]), 4) for k in range(4)},
            category=SCORE_NAMES[pred], confidence=float(probs[order[0]]), margin=float(probs[order[0]] - probs[order[1]]),
            runner_up=SCORE_NAMES[int(order[1])], borderline=bool(abs(int(order[0]) - int(order[1])) == 1 and probs[order[0]] - probs[order[1]] < 0.25),
            tiles=regions, grid=(rows, cols),
            heterogeneity={"regions_by_grade": share, "grade_spread": int(spread), "heterogeneous": bool(heterogeneous),
                           "regions_with_tissue": len(tissue_regions)},
            evidence_map=heat, model=self.info)


def evidence_overlay(rgb: np.ndarray, heat: np.ndarray, alpha: float = 0.55) -> np.ndarray:
    """Grad-CAM heat (blue -> yellow -> red) over a greyed field."""
    grey = rgb.astype(np.float32).mean(-1, keepdims=True).repeat(3, -1) * 0.6 + 255 * 0.4
    h = np.clip(heat, 0, 1)[..., None]
    colour = np.concatenate([np.clip(2 * h, 0, 1), np.clip(2 - 2 * np.abs(h - 0.5) * 2, 0, 1) * (h > 0.25), np.clip(1 - 2 * h, 0, 1) * 0.6], -1) * 255
    w = np.clip(h * 1.4, 0, 1) * alpha
    return np.clip(grey * (1 - w) + colour * w, 0, 255).astype(np.uint8)


def regions_overlay(rgb: np.ndarray, result: PrescoreResult) -> np.ndarray:
    """Each tile tinted by its own pre-score; border thickness shows its attention weight."""
    out = rgb.astype(np.float32).copy()
    max_att = max([g["attention"] for g in result.tiles] or [1.0])
    for g in result.tiles:
        y0, x0 = g["row"] * TILE, g["col"] * TILE
        y1, x1 = min(y0 + TILE, rgb.shape[0]), min(x0 + TILE, rgb.shape[1])
        if y0 >= y1 or x0 >= x1 or g["tissue_fraction"] < 0.15:
            continue
        col = np.array(GRADE_COLORS[g["category"]], dtype=np.float32)
        out[y0:y1, x0:x1] = out[y0:y1, x0:x1] * 0.65 + col * 0.35
        t = max(3, int(14 * g["attention"] / max_att))
        out[y0:y0 + t, x0:x1] = col
        out[y1 - t:y1, x0:x1] = col
        out[y0:y1, x0:x0 + t] = col
        out[y0:y1, x1 - t:x1] = col
    return np.clip(out, 0, 255).astype(np.uint8)


# ------------------------------------------------------------- whole slides


@torch.no_grad()
def embed_field(engine: PrescoreEngine, rgb: np.ndarray) -> tuple[torch.Tensor, np.ndarray]:
    """Tile embeddings (T, 512) and per-tile grade probabilities (T, 4) for one 40x field."""
    tiles, _, _, _ = engine._tiles(rgb)
    m = engine.model
    pixels = gpu_ops.model_input(tiles).to(engine.device)
    _, feats = m.unet(m.standardize(pixels), return_features=True, with_seg=False)
    emb = m.embed(torch.cat([feats.mean((2, 3)), feats.amax((2, 3))], 1))
    return emb.cpu(), F.softmax(m.score_head(emb).float(), -1).cpu().numpy()


@torch.no_grad()
def pool_slide(engine: PrescoreEngine, embeddings: torch.Tensor) -> tuple[dict, np.ndarray]:
    """Slide-level pre-score: the same attention pooling and score head over ALL tumour tiles of a slide."""
    m = engine.model
    emb = embeddings.to(engine.device)
    bag, attention = m.pool(emb, [emb.shape[0]])
    probs = F.softmax(m.score_head(bag)[0].float(), -1).cpu().numpy()
    order = np.argsort(-probs)
    public = {"category": SCORE_NAMES[int(order[0])], "probabilities": {SCORE_NAMES[k]: round(float(probs[k]), 4) for k in range(4)},
              "confidence": round(float(probs[order[0]]), 3), "margin_to_runner_up": round(float(probs[order[0]] - probs[order[1]]), 3),
              "runner_up": SCORE_NAMES[int(order[1])],
              "borderline": bool(abs(int(order[0]) - int(order[1])) == 1 and probs[order[0]] - probs[order[1]] < 0.25),
              "model": engine.info}
    return public, attention[0].cpu().numpy()
