"""Site-Adaptive HER2 Calibration on a new hospital, scored once on its test split.

    python scripts/adapt_v2.py --config configs/v2_adapt_bci.yaml

Starts from a trained multi-task checkpoint (Run A: never saw BCI) and
adapts it to BCI using BCI *train* images with their labels stripped
(training/site_adapt.py). Then scores BCI *test* under each stage, so the
contribution of every stage is visible:

    A0  as scanned                                    (Run A, unchanged)
    A1  + site-level stain normalization              (stage 1)
    A2  + BatchNorm adaptation                        (stage 3)
    A3  + intensity-preserving self-training + BN     (stage 4; the primary result)

All hyperparameters are fixed in the config before this runs; nothing is
tuned on BCI test, and no checkpoint is selected with it (A3 = final step).
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import torch  # noqa: E402

from evaluation.score_metrics import paired_bootstrap, score_metrics  # noqa: E402
from preprocessing.config import PreprocessingConfig  # noqa: E402
from training.site_adapt import adapt_batchnorm, self_train, unlabelled  # noqa: E402
from training.v2_data import bci_samples, her2_ihc_40x_samples  # noqa: E402
from training.v2_engine import _amp_dtype, load_model, predict  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    from train_v2 import load_config

    cfg = load_config(args.config)
    acfg = cfg["adapt"]
    out_dir = ROOT / "artifacts" / "v2" / cfg["run_name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    log_file = (out_dir / "adapt.log").open("a", encoding="utf-8")

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
    site_norm = {"bci": (profiles["bci_crop2x"], profiles["source"])}
    limit = acfg.get("limit_per_class")
    workers = int(cfg["train"].get("workers", 4))
    batch = int(cfg.get("eval", {}).get("batch", 4))

    test = bci_samples(rp("bci_root"), "test", limit_per_class=limit)
    target_pool = unlabelled(bci_samples(rp("bci_root"), "fit", limit_per_class=limit)
                             + bci_samples(rp("bci_root"), "val", limit_per_class=limit))
    source = her2_ihc_40x_samples(rp("her2_root"), rp("her2_split"), "fit", limit, cfg.get("seed", 0))
    subset = set((ROOT / cfg["data"]["bci_subset_list"]).read_text().split()) if cfg["data"].get("bci_subset_list") else set()
    log(f"adapt {cfg['run_name']}: test {len(test)}, unlabelled target pool {len(target_pool)}, source {len(source)}")

    results, preds = {"stages": {}}, {}

    def score(name, model, sn):
        rows = predict(model, test, device, prep, batch, workers, site_norm=sn, amp_dtype=amp)
        preds[name] = rows
        y, p = [r["label"] for r in rows], [r["pred"] for r in rows]
        entry = {"metrics": score_metrics(y, p)}
        sub = [r for r in rows if Path(r["path"]).name in subset]
        if sub:
            entry["metrics_subset338"] = score_metrics([r["label"] for r in sub], [r["pred"] for r in sub])
        results["stages"][name] = entry
        m = entry["metrics"]
        log(f"{name}: acc {m['accuracy']:.4f} bal {m['balanced_accuracy']:.4f} QWK {m['qwk']:.4f} within-one {m['within_one']:.3f} (n={m['n']})")

    checkpoint = ROOT / acfg["checkpoint"]
    model = load_model(checkpoint, device)
    score("A0_as_scanned", model, None)
    score("A1_site_norm", model, site_norm)

    model = load_model(checkpoint, device)
    results["bn_adapt"] = adapt_batchnorm(model, target_pool, device, prep, alpha=float(acfg.get("bn_alpha", 1.0)),
                                          max_bags=int(acfg.get("bn_max_bags", 600)), workers=workers,
                                          site_norm=site_norm, amp_dtype=amp)
    score("A2_site_norm_bn", model, site_norm)

    results["self_train"] = self_train(model, source, target_pool, device, prep, cfg, site_norm=site_norm, log=log)
    results["bn_readapt"] = adapt_batchnorm(model, target_pool, device, prep, alpha=float(acfg.get("bn_alpha", 1.0)),
                                            max_bags=int(acfg.get("bn_max_bags", 600)), workers=workers,
                                            site_norm=site_norm, amp_dtype=amp)
    score("A3_site_norm_bn_selftrain", model, site_norm)
    torch.save({"model_state": model.state_dict(), "model_config": model.config, "config": cfg}, out_dir / "adapted.pt")

    y = [r["label"] for r in preds["A0_as_scanned"]]
    base = [r["pred"] for r in preds["A0_as_scanned"]]
    results["vs_A0"] = {k: paired_bootstrap(y, base, [r["pred"] for r in v]) for k, v in preds.items() if k != "A0_as_scanned"}
    (out_dir / "adapt_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    lines = ["| Stage | Accuracy | Balanced | Macro-F1 | QWK | Within one |", "|---|---|---|---|---|---|"]
    for k, e in results["stages"].items():
        m = e["metrics"]
        lines.append(f"| {k} | {m['accuracy']:.3f} | {m['balanced_accuracy']:.3f} | {m['macro_f1']:.3f} | {m['qwk']:.3f} | {m['within_one']:.3f} |")
    (out_dir / "adapt_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    log("adaptation done")


if __name__ == "__main__":
    main()
