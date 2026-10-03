"""Train the invasive-tumour segmenter (wsi/tumour.py) on TIGER H&E annotations.

    python scripts/train_tumour.py --config configs/tumour_seg.yaml

Data: TIGER WSIROIS tissue-cells ROIs (images + masks, ~0.5 um/px; TCGA,
Radboud, Bordet), downloaded to ``data/external/tiger/tissue-cells``.

Protocol (fixed before training):
* split by SLIDE (the filename prefix before "__"): 15% of slides held out
  for validation, stratified by source (TCGA vs non-TCGA);
* input = haematoxylin-only rendering (wsi/tumour.py), so the model never
  sees eosin and can be applied to HER2 IHC;
* model selection = best validation IoU for INVASIVE tumour;
* after training, an IHC transfer check: predicted invasive-tumour fraction
  on HER2-IHC-40x holdout patches and BCI test patches -- both cut from
  tumour regions, so a high fraction is expected; a low one would mean the
  H&E-to-IHC transfer failed.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402
import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from PIL import Image  # noqa: E402

from wsi.tumour import IGNORE, TIGER_TO_OURS, TUMOUR_CLASSES, _standardize, build_segmenter, haematoxylin_image  # noqa: E402

LUT = np.full(256, IGNORE, dtype=np.uint8)
for k, v in TIGER_TO_OURS.items():
    LUT[k] = v


def pairs(root: Path) -> list[tuple[Path, Path, str]]:
    out = []
    for img in sorted((root / "images").glob("*.png")):
        mask = root / "masks" / img.name
        if mask.is_file():
            out.append((img, mask, img.name.split("__")[0]))
    return out


def split_by_slide(items, val_fraction: float, seed: int):
    rng = random.Random(seed)
    slides = sorted({s for _, _, s in items})
    tcga = [s for s in slides if s.startswith("TCGA")]
    other = [s for s in slides if not s.startswith("TCGA")]
    val = set()
    for group in (tcga, other):
        rng.shuffle(group)
        val |= set(group[: max(1, int(round(len(group) * val_fraction)))])
    return [i for i in items if i[2] not in val], [i for i in items if i[2] in val]


class RoiDataset(torch.utils.data.Dataset):
    def __init__(self, items, crop: int, train: bool, samples: int | None = None) -> None:
        self.items, self.crop, self.train = items, crop, train
        self.samples = samples or len(items)

    def __len__(self) -> int:
        return self.samples

    def __getitem__(self, i: int):
        img_p, mask_p, _ = self.items[random.randrange(len(self.items)) if self.train else i % len(self.items)]
        img = np.asarray(Image.open(img_p).convert("RGB"))
        mask = LUT[np.asarray(Image.open(mask_p))]
        h, w = mask.shape
        c = self.crop
        if h < c or w < c:
            ph, pw = max(0, c - h), max(0, c - w)
            img = np.pad(img, ((0, ph), (0, pw), (0, 0)), constant_values=255)
            mask = np.pad(mask, ((0, ph), (0, pw)), constant_values=IGNORE)
            h, w = mask.shape
        if self.train:
            y, x = random.randint(0, h - c), random.randint(0, w - c)
        else:
            y, x = (h - c) // 2, (w - c) // 2
        img, mask = img[y:y + c, x:x + c], mask[y:y + c, x:x + c]
        hscale = random.uniform(0.75, 1.3) if self.train else 1.0
        himg = haematoxylin_image(img, "he", h_scale=hscale)
        if self.train:
            k = random.randint(0, 3)
            himg, mask = np.rot90(himg, k), np.rot90(mask, k)
            if random.random() < 0.5:
                himg, mask = himg[:, ::-1], mask[:, ::-1]
            if random.random() < 0.3:
                from scipy import ndimage

                himg = ndimage.gaussian_filter(himg, sigma=(random.uniform(0.3, 1.2),) * 2 + (0,))
        x_t = torch.from_numpy(np.ascontiguousarray(himg)).permute(2, 0, 1).float().div(255.0)
        return x_t, torch.from_numpy(np.ascontiguousarray(mask)).long()


def dice_loss(logits, target, num_classes):
    valid = (target != IGNORE).unsqueeze(1)
    t = F.one_hot(target.clamp(max=num_classes - 1), num_classes).permute(0, 3, 1, 2).float() * valid
    p = F.softmax(logits.float(), 1) * valid
    inter = (p * t).sum((0, 2, 3))
    denom = p.sum((0, 2, 3)) + t.sum((0, 2, 3))
    return 1 - ((2 * inter + 1) / (denom + 1)).mean()


@torch.no_grad()
def evaluate(model, loader, device, weights, n_classes):
    model.eval()
    inter = np.zeros(n_classes)
    union = np.zeros(n_classes)
    tp = fp = fn = 0
    for x, y in loader:
        x, y = x.to(device), y.to(device)
        with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
            pred = model(_standardize(x, weights)).argmax(1)
        valid = y != IGNORE
        for c in range(n_classes):
            a, b = (pred == c) & valid, (y == c) & valid
            inter[c] += (a & b).sum().item()
            union[c] += (a | b).sum().item()
        tp += ((pred == 1) & (y == 1) & valid).sum().item()
        fp += ((pred == 1) & (y != 1) & valid).sum().item()
        fn += ((pred != 1) & (y == 1) & valid).sum().item()
    iou = {TUMOUR_CLASSES[c]: float(inter[c] / union[c]) if union[c] else None for c in range(n_classes)}
    prec, rec = tp / max(1, tp + fp), tp / max(1, tp + fn)
    return {"iou": iou, "invasive_precision": prec, "invasive_recall": rec,
            "invasive_f1": 2 * prec * rec / max(1e-9, prec + rec)}


@torch.no_grad()
def ihc_transfer_check(model, device, weights, cfg, log) -> dict:
    """Predicted invasive fraction of tissue on IHC patches cut from tumour regions."""
    from preprocessing.config import PreprocessingConfig
    from preprocessing.tissue import detect_tissue
    from training.v2_data import bci_samples, her2_ihc_40x_samples

    prep = PreprocessingConfig.from_yaml(ROOT / "configs" / "preprocessing.yaml")
    out = {}
    sets = {}
    try:
        sets["her2_ihc_40x_holdout"] = (her2_ihc_40x_samples(ROOT / cfg["her2_root"], ROOT / "configs/splits/her2_ihc_40x_split.json",
                                                             "holdout", 50, 0), 0.24)
    except FileNotFoundError:
        pass
    try:
        sets["bci_test"] = (bci_samples(ROOT / cfg["bci_root"], "test", limit_per_class=50), 0.46)
    except FileNotFoundError:
        pass
    model.eval()
    for name, (samples, mpp) in sets.items():
        fracs = []
        for s in samples:
            im = Image.open(s.path).convert("RGB")
            f = mpp / 0.5
            im = im.resize((max(64, int(im.width * f)), max(64, int(im.height * f))), Image.LANCZOS)
            rgb = np.asarray(im)
            tissue = detect_tissue(rgb, prep.tissue)
            x = torch.from_numpy(haematoxylin_image(rgb, "ihc", tissue=tissue)).permute(2, 0, 1)[None].float().div(255).to(device)
            ph, pw = (-x.shape[-2]) % 32, (-x.shape[-1]) % 32
            x = F.pad(x, (0, pw, 0, ph), value=1.0)
            pred = model(_standardize(x, weights)).argmax(1)[0, : rgb.shape[0], : rgb.shape[1]].cpu().numpy()
            if tissue.sum() > 100:
                fracs.append(float((pred[tissue] == 1).mean()))
        out[name] = {"n": len(fracs), "mean_invasive_fraction": float(np.mean(fracs)) if fracs else None,
                     "share_with_invasive_over_30pct": float(np.mean([f > 0.3 for f in fracs])) if fracs else None}
        log(f"IHC transfer check {name}: {out[name]}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    import yaml

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    out_dir = ROOT / cfg.get("output_dir", "artifacts/tumour")
    out_dir.mkdir(parents=True, exist_ok=True)
    logf = (out_dir / "train.log").open("a", encoding="utf-8")

    def log(m):
        line = f"[{time.strftime('%H:%M:%S')}] {m}"
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    seed = int(cfg.get("seed", 0))
    random.seed(seed)
    torch.manual_seed(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type != "cuda" and cfg.get("require_gpu", True):
        raise SystemExit("No usable GPU and require_gpu is true.")
    items = pairs(ROOT / cfg["tiger_root"])
    if cfg.get("limit_images"):
        items = items[: int(cfg["limit_images"])]
    train_items, val_items = split_by_slide(items, float(cfg.get("val_fraction", 0.15)), seed)
    log(f"{len(items)} ROIs: train {len(train_items)} ({len({s for *_, s in train_items})} slides), "
        f"val {len(val_items)} ({len({s for *_, s in val_items})} slides)")
    crop, bs, workers = int(cfg.get("crop", 512)), int(cfg.get("batch", 8)), int(cfg.get("workers", 6))
    train_dl = torch.utils.data.DataLoader(RoiDataset(train_items, crop, True, int(cfg.get("samples_per_epoch", 2000))),
                                           batch_size=bs, num_workers=workers, drop_last=True, persistent_workers=workers > 0)
    val_dl = torch.utils.data.DataLoader(RoiDataset(val_items, crop, False), batch_size=bs, num_workers=workers)
    weights = cfg.get("encoder_weights", "lunit_bt")
    model = build_segmenter(cfg.get("encoder", "resnet50"), weights).to(device).to(memory_format=torch.channels_last)
    n_cls = len(TUMOUR_CLASSES)
    class_w = torch.tensor(cfg.get("class_weights", [1.0, 1.0, 1.5, 1.5]), device=device)
    opt = torch.optim.AdamW(model.parameters(), lr=float(cfg.get("lr", 3e-4)), weight_decay=1e-4)
    epochs = int(cfg.get("epochs", 20))
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=float(cfg.get("lr", 3e-4)), total_steps=epochs * len(train_dl), pct_start=0.05)
    best, history, started = -1.0, [], time.time()
    max_seconds = float(cfg.get("max_minutes", 1e9)) * 60
    for epoch in range(epochs):
        model.train()
        losses = []
        for x, y in train_dl:
            x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
            with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                logits = model(_standardize(x, weights).contiguous(memory_format=torch.channels_last))
            loss = F.cross_entropy(logits.float(), y, weight=class_w, ignore_index=IGNORE) + 0.5 * dice_loss(logits, y, n_cls)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            losses.append(float(loss.detach()))
        m = evaluate(model, val_dl, device, weights, n_cls)
        rec = {"epoch": epoch + 1, "loss": round(float(np.mean(losses)), 4), "minutes": round((time.time() - started) / 60, 1),
               "invasive_iou": m["iou"]["invasive tumour"], "invasive_f1": round(m["invasive_f1"], 4), "iou": m["iou"]}
        history.append(rec)
        log(json.dumps(rec))
        score = m["iou"]["invasive tumour"] or 0.0
        if score > best:
            best = score
            torch.save({"model_state": model.state_dict(), "model_config": {"encoder": cfg.get("encoder", "resnet50"), "encoder_weights": weights},
                        "metrics": m, "epoch": epoch + 1}, out_dir / "best.pt")
            log(f"  new best invasive IoU {best:.4f}")
        if time.time() - started > max_seconds:
            log("wall-clock cap reached")
            break
    ck = torch.load(out_dir / "best.pt", map_location=device, weights_only=False)
    model.load_state_dict(ck["model_state"])
    transfer = ihc_transfer_check(model, device, weights, cfg, log)
    ck["ihc_transfer"] = transfer
    torch.save(ck, out_dir / "best.pt")
    (out_dir / "results.json").write_text(json.dumps({"best_epoch": ck["epoch"], "val": ck["metrics"], "ihc_transfer": transfer,
                                                     "history": history}, indent=2), encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
