"""Render model predictions beside the targets they were trained against.

    python scripts/predict_preview.py --run artifacts/phase2 --count 8

Metrics say a class is being missed; only a picture says *how*. This draws, for
a few validation patches, the input, the pseudo-label target and the model's
prediction side by side, plus a disagreement map.

Validation patches, not held-out ones: the held-out set is not spent in
Phase 2 (see training/train.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

from models.segformer_seg import build_model, normalize_batch
from preprocessing.baseline import CLASS_NAMES, NUM_CLASSES
from preprocessing.sources import DirectoryPatchSource
from training.config import TrainingConfig
from training.pseudo_labels import PseudoLabelCache
from training.splits import stratified_subsample

INTENSITY_COLORS = ["#f0f0f0", "#cfd8dc", "#ffd699", "#e08214", "#8c3d04"]
INTENSITY_CMAP = ListedColormap(INTENSITY_COLORS)
DISAGREE_CMAP = ListedColormap(["#d62728"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="artifacts/phase2")
    parser.add_argument("--config", default="configs/training.yaml")
    parser.add_argument("--count", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run = Path(args.run)
    config = TrainingConfig.from_yaml(args.config)

    checkpoint = torch.load(run / "best.pt", map_location="cpu", weights_only=False)
    model = build_model(config.model, verbose=False)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()
    print(f"Loaded epoch {checkpoint['epoch']} from {run / 'best.pt'}")

    split = json.loads((run / "split.json").read_text(encoding="utf-8"))
    cache = PseudoLabelCache(config.data.cache_root)
    source = DirectoryPatchSource(config.data.patch_root, splits=["train", "test"])

    available = [p for p in split["patch_ids"]["val"] if cache.tile_ids(p)]
    parents = stratified_subsample(source, available, args.count, config.seed)
    # One tile per parent patch, so the preview shows variety of specimen
    # rather than four views of the same one.
    chosen = [cache.tile_ids(p)[0] for p in parents]

    fig, axes = plt.subplots(len(chosen), 4, figsize=(12, 3 * len(chosen)), squeeze=False)
    for row, patch_id in enumerate(chosen):
        rgb, target = cache.read(patch_id)
        pixels = torch.from_numpy(rgb).permute(2, 0, 1).float()[None] / 255.0
        with torch.no_grad():
            prediction = model(normalize_batch(pixels)).argmax(dim=1)[0].numpy()

        folder = CLASS_NAMES[source.label(cache.parent_of(patch_id))]
        panels = [
            (rgb, f"input -- folder label: {folder}", None),
            (target, "pseudo-label target", INTENSITY_CMAP),
            (prediction, "model prediction", INTENSITY_CMAP),
        ]
        for col, (data, title, cmap) in enumerate(panels):
            if cmap is None:
                axes[row][col].imshow(data)
            else:
                axes[row][col].imshow(
                    data, cmap=cmap, vmin=0, vmax=NUM_CLASSES - 1,
                    interpolation="nearest",
                )
            axes[row][col].set_title(title, fontsize=7.5)

        disagree = prediction != target
        axes[row][3].imshow(rgb)
        axes[row][3].imshow(
            np.ma.masked_where(~disagree, disagree.astype(float)),
            cmap=DISAGREE_CMAP, vmin=0, vmax=1, alpha=0.5, interpolation="nearest",
        )
        axes[row][3].set_title(
            f"disagreement ({disagree.mean() * 100:.1f}% of pixels)", fontsize=7.5
        )
        for ax in axes[row]:
            ax.set_xticks([])
            ax.set_yticks([])

    handles = [
        Patch(facecolor=INTENSITY_COLORS[c], edgecolor="#555555", label=CLASS_NAMES[c])
        for c in range(NUM_CLASSES)
    ]
    fig.legend(handles=handles, loc="lower center", ncol=NUM_CLASSES, fontsize=8)
    fig.suptitle(
        "Phase 2 predictions vs DAB-threshold targets (validation patches)",
        fontsize=11,
    )
    fig.tight_layout(rect=(0, 0.035, 1, 0.975))
    out = run / "prediction_preview.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
