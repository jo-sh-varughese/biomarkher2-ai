"""Tile embeddings for the learning loop: replay set, locked reference set, and BCI (simulation).

    python scripts/extract_learning_features.py --checkpoint artifacts/v2/run_a/best.pt --out artifacts/learning/features_run_a.npz

For each image: the model's tile embeddings (T x 512, the input of its attention
pooling and score head), the label, and an id. Preprocessing is exactly the
evaluation pipeline's (training/v2_engine.prepare_batch), so the numbers match
artifacts/v2/*/eval.json.

Sets:
* ``replay`` -- training-site FIT images (balanced): mixed into every update so
  the model keeps what each grade means (no forgetting);
* ``reference`` -- training-site HOLDOUT images (balanced): the LOCKED set every
  candidate must not get worse on;
* ``bci`` -- all local BCI images (train + test folders), quad2x view: the
  simulated new hospital.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import torch  # noqa: E402

from preprocessing.config import PreprocessingConfig  # noqa: E402
from training.v2_data import ImageDataset, Sample, bci_score, collate, her2_ihc_40x_samples  # noqa: E402
from training.v2_engine import load_model, prepare_batch  # noqa: E402


@torch.no_grad()
def embed(model, samples: list[Sample], prep, batch: int = 2) -> list[np.ndarray]:
    loader = torch.utils.data.DataLoader(ImageDataset(samples, train=False), batch_size=batch, shuffle=False,
                                         num_workers=0, collate_fn=collate)
    out = []
    for i, b in enumerate(loader):
        pixels, bag_sizes, _ = prepare_batch(b, torch.device("cpu"), prep, aug=None, need_seg_labels=False)
        _, feats = model.unet(model.standardize(pixels), return_features=True, with_seg=False)
        emb = model.embed(torch.cat([feats.mean((2, 3)), feats.amax((2, 3))], 1)).numpy().astype(np.float16)
        out += np.split(emb, np.cumsum(bag_sizes)[:-1])
        if (i + 1) % 25 == 0:
            print(f"  {len(out)}/{len(samples)}", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-class", type=int, default=100, help="replay and reference images per grade")
    ap.add_argument("--sets", default="replay,reference,bci", help="which sets to extract (comma-separated)")
    args = ap.parse_args()
    torch.set_num_threads(max(1, torch.get_num_threads()))
    prep = PreprocessingConfig.from_yaml(ROOT / "configs/preprocessing.yaml")
    model = load_model(Path(args.checkpoint), torch.device("cpu")).float().eval()
    split = ROOT / "configs/splits/her2_ihc_40x_split.json"
    sets = {
        "replay": her2_ihc_40x_samples(ROOT / "data/raw", split, "fit", args.per_class, seed=1),
        "reference": her2_ihc_40x_samples(ROOT / "data/raw", split, "holdout", args.per_class, seed=2),
        "bci": [Sample(str(p), "bci", bci_score(p.name), bci_score(p.name), False, "quad2x")
                for d in ("IHC_train", "IHC_test") for p in sorted((ROOT / "data/external/bci" / d).glob("*.png"))],
    }
    wanted = set(args.sets.split(","))
    sets = {k: v for k, v in sets.items() if k in wanted}
    data = {}
    for name, samples in sets.items():
        print(f"{name}: {len(samples)} images", flush=True)
        embs = embed(model, samples, prep)
        data[f"{name}_emb"] = np.array(embs, dtype=object)
        data[f"{name}_label"] = np.array([s.label for s in samples])
        data[f"{name}_id"] = np.array([Path(s.path).name for s in samples])
        data[f"{name}_group"] = np.array([Path(s.path).parent.name for s in samples])
    Path(ROOT / args.out).parent.mkdir(parents=True, exist_ok=True)
    np.savez(ROOT / args.out, **data, checkpoint=str(args.checkpoint))
    print("wrote", args.out)


if __name__ == "__main__":
    main()
