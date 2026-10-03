"""New-hospital onboarding with a fixed budget of labelled cases (Kottayam: 25 slides).

    python scripts/fewshot_v2.py --config configs/v2_fewshot_bci.yaml

For each budget mix (e.g. 25 cases balanced, or 25 in Kottayam's score
proportions) and each random draw:

1. Draw that many labelled cases from BCI's *train* split.
2. Stain correction: among ``dab_scales`` (which include the site
   fingerprint's label-free estimate), keep the site-level DAB scale that
   gives the starting model (Run A) the best accuracy on THOSE labelled cases.
   The test split is never used for any choice.
3. Fine-tune Run A on those cases at that correction, mixed 1:1 with
   labelled replay from our own data so the meaning of each score is kept.
4. Score BCI's whole test split once.

A zero-label row (fingerprint's DAB scale, Run A unchanged) is the reference.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import torch  # noqa: E402

from evaluation.score_metrics import score_metrics  # noqa: E402
from preprocessing.config import PreprocessingConfig  # noqa: E402
from training.v2_data import ImageDataset, balanced_sampler, bci_samples, collate, her2_ihc_40x_samples  # noqa: E402
from training.v2_engine import MultiTaskLoss, _amp_dtype, load_model, predict, prepare_batch  # noqa: E402


def site_norm_at(profiles: dict, dab_scale: float) -> dict:
    """BCI -> our stain vectors; haematoxylin at its fitted ratio, DAB scaled by ``dab_scale``."""
    src, bci = profiles["source"], dict(profiles["bci_crop2x"])
    h_ratio = src["concentration_p99"][0] / bci["concentration_p99"][0]
    bci["concentration_p99"] = [src["concentration_p99"][0] / h_ratio, src["concentration_p99"][1] / dab_scale]
    return {"bci": (bci, src)}


def draw(pool, per_class: list[int], seed: int):
    rng = random.Random(seed)
    out = []
    for label, n in enumerate(per_class):
        group = sorted([s for s in pool if s.label == label], key=lambda s: s.path)
        rng.shuffle(group)
        out += group[:n]
    return out


def merge(a: dict, b: dict) -> dict:
    return {key: (a[key] + b[key]) if isinstance(a[key], list) else torch.cat([a[key], b[key]]) for key in a}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    from train_v2 import load_config

    cfg = load_config(args.config)
    fcfg = cfg["fewshot"]
    out_dir = ROOT / "artifacts" / "v2" / cfg["run_name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    log_file = (out_dir / "fewshot.log").open("a", encoding="utf-8")

    def log(msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        log_file.write(line + "\n")
        log_file.flush()

    def rp(key):
        p = Path(cfg["data"][key])
        return p if p.is_absolute() else ROOT / p

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type != "cuda" and cfg["train"].get("require_gpu", True):
        raise SystemExit("No usable GPU and train.require_gpu is true.")
    amp = _amp_dtype(device)
    prep = PreprocessingConfig.from_yaml(ROOT / "configs" / "preprocessing.yaml")
    profiles = json.loads((ROOT / cfg["data"]["site_profiles"]).read_text(encoding="utf-8"))
    workers = int(cfg["train"].get("workers", 4))
    batch = int(cfg.get("eval", {}).get("batch", 4))
    limit = fcfg.get("limit_per_class")
    test = bci_samples(rp("bci_root"), "test", limit_per_class=limit)
    pool = bci_samples(rp("bci_root"), "fit")
    source = her2_ihc_40x_samples(rp("her2_root"), rp("her2_split"), "fit", limit, cfg.get("seed", 0))
    subset = set((ROOT / cfg["data"]["bci_subset_list"]).read_text().split())
    checkpoint = ROOT / fcfg["checkpoint"]
    scales = [float(s) for s in fcfg["dab_scales"]]
    label_free = float(fcfg["label_free_dab_scale"])
    results_path = out_dir / "fewshot_results.json"
    results = json.loads(results_path.read_text()) if results_path.exists() else {"runs": []}
    done = {(r["budget"], r["seed"]) for r in results["runs"]}

    def evaluate(model, sn):
        rows = predict(model, test, device, prep, batch, workers, site_norm=sn, amp_dtype=amp)
        m = score_metrics([r["label"] for r in rows], [r["pred"] for r in rows])
        sub = [r for r in rows if Path(r["path"]).name in subset]
        return m, (score_metrics([r["label"] for r in sub], [r["pred"] for r in sub]) if sub else None)

    def save():
        results_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    if ("zero_labels", 0) not in done:
        m, m338 = evaluate(load_model(checkpoint, device), site_norm_at(profiles, label_free))
        results["runs"].append({"budget": "zero_labels", "seed": 0, "n_labelled": 0, "dab_scale": label_free,
                                "metrics": m, "metrics_subset338": m338})
        log(f"zero labels (fingerprint DAB x{label_free}): acc {m['accuracy']:.4f} bal {m['balanced_accuracy']:.4f} QWK {m['qwk']:.4f}")
        save()

    for budget, spec in fcfg["budgets"].items():
        for seed in fcfg["seeds"]:
            if (budget, seed) in done:
                continue
            started = time.time()
            labelled = draw(pool, spec, seed)
            model = load_model(checkpoint, device)
            as_eval = [dataclasses.replace(s, view="quad2x") for s in labelled]
            scale_acc = {}
            for scale in scales:
                rows = predict(model, as_eval, device, prep, batch, workers, site_norm=site_norm_at(profiles, scale), amp_dtype=amp)
                scale_acc[scale] = sum(r["pred"] == r["label"] for r in rows) / len(rows)
            best = max(scales, key=lambda s: (scale_acc[s], -abs(s - label_free)))
            sn = site_norm_at(profiles, best)
            criterion = MultiTaskLoss(cfg.get("loss", {})).to(device)
            optimizer = torch.optim.AdamW(model.parameters(), lr=float(fcfg["lr"]), weight_decay=1e-4)
            steps, half = int(fcfg["steps"]), int(fcfg.get("bags_each", 2))
            tgt = iter(torch.utils.data.DataLoader(
                ImageDataset(labelled, train=True), batch_size=half, num_workers=workers, collate_fn=collate, drop_last=True,
                sampler=torch.utils.data.RandomSampler(labelled, replacement=True, num_samples=steps * half,
                                                       generator=torch.Generator().manual_seed(seed))))
            src = iter(torch.utils.data.DataLoader(
                ImageDataset(source, train=True), batch_size=half, num_workers=workers, collate_fn=collate, drop_last=True,
                sampler=balanced_sampler(source, steps * half, seed=seed)))
            model.train()
            for _ in range(steps):
                b = merge(next(tgt), next(src))
                px, bags, seg = prepare_batch(b, device, prep, aug=cfg["augment"], site_norm=sn)
                with torch.autocast(device.type, dtype=amp, enabled=amp is not None):
                    out = model(px.contiguous(memory_format=torch.channels_last), bags, with_seg=seg is not None)
                loss, _ = criterion(out, b["label"].to(device), seg)
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
            model.eval()
            m, m338 = evaluate(model, sn)
            results["runs"].append({"budget": budget, "seed": seed, "per_class": spec, "n_labelled": len(labelled),
                                    "dab_scale": best, "dab_scale_acc_on_labelled": scale_acc, "metrics": m,
                                    "metrics_subset338": m338, "minutes": (time.time() - started) / 60})
            log(f"{budget} seed {seed} (n={len(labelled)}, DAB x{best}): acc {m['accuracy']:.4f} bal {m['balanced_accuracy']:.4f} "
                f"QWK {m['qwk']:.4f} [{(time.time() - started) / 60:.1f} min]")
            save()
    log("fewshot done")


if __name__ == "__main__":
    main()
