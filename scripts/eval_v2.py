"""Evaluate a trained multi-task U-Net against the pre-registered targets.

    python scripts/eval_v2.py --config configs/v2_run_a.yaml [--checkpoint path]

Test sets (never used for training or model selection):
* ``her2_ihc_40x_holdout`` -- our reserved holdout split (filename origin
  "test"). Scored against the patch label (primary) and the slide label.
* ``bci_test`` -- all of BCI's test split, scored on the whole field
  (four quadrants at matched scale). Also reported on the 338-image subset
  used in docs/CROSS_SITE_STAIN_NORMALIZATION.md, for a like-for-like
  comparison with the old model's 39.9%.

Each external set is scored raw and with site-level stain normalization
toward the training site. Which sets count as "in-domain" and "unseen
site" follows from the run's train_sites. Writes ``eval.json``,
``predictions.csv`` and ``eval_summary.md`` next to the checkpoint.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import torch  # noqa: E402

from evaluation.score_metrics import meets_targets, paired_bootstrap, score_metrics  # noqa: E402
from preprocessing.config import PreprocessingConfig  # noqa: E402
from training.v2_data import bci_samples, her2_ihc_40x_samples  # noqa: E402


def _site_norm(cfg: dict) -> dict:
    """Normalize the OTHER site toward the training site's stain profile."""
    path = ROOT / cfg["data"].get("site_profiles", "configs/site_profiles/her2_ihc_40x_vs_bci.json")
    profiles = json.loads(path.read_text(encoding="utf-8"))
    source, bci = profiles["source"], profiles["bci_crop2x"]
    if cfg["data"].get("train_site_norm") or "her2_ihc_40x" in cfg["data"]["train_sites"]:
        # Shared stain space (or trained on our site): our reference space is the model's space.
        return {"bci": (bci, source)}
    return {"her2_ihc_40x": (source, bci)}


def evaluate_run(cfg: dict, out_dir: Path, checkpoint: Path | None = None, log=print) -> dict:
    from training.v2_engine import _amp_dtype, load_model, predict

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    prep = PreprocessingConfig.from_yaml(ROOT / "configs" / "preprocessing.yaml")
    model = load_model(checkpoint or out_dir / "best.pt", device)
    ecfg = cfg.get("eval", {})
    batch = int(ecfg.get("batch", cfg["train"].get("eval_batch", 4)))
    workers = int(cfg["train"].get("workers", 4))
    limit = ecfg.get("limit_per_class")
    amp = _amp_dtype(device)
    trained_on = set(cfg["data"]["train_sites"])
    targets = cfg.get("targets", {})

    def rp(key):
        p = Path(cfg["data"][key])
        return p if p.is_absolute() else ROOT / p

    wanted = ecfg.get("sets", ["her2_ihc_40x_holdout", "bci_test"])
    sets = {}
    if "her2_ihc_40x_holdout" in wanted:
        sets["her2_ihc_40x_holdout"] = her2_ihc_40x_samples(rp("her2_root"), rp("her2_split"), "holdout", limit, cfg.get("seed", 0))
    if "bci_test" in wanted:
        sets["bci_test"] = bci_samples(rp("bci_root"), "test", limit_per_class=limit)
    subset_file = cfg["data"].get("bci_subset_list")
    subset = set()
    if subset_file and (ROOT / subset_file).is_file():
        subset = {line.strip() for line in (ROOT / subset_file).read_text().splitlines() if line.strip()}

    norm = _site_norm(cfg) if ecfg.get("site_norm", True) else {}
    results, all_rows = {"run": cfg["run_name"], "trained_on": sorted(trained_on), "sets": {}}, []
    for name, samples in sets.items():
        site = samples[0].site
        role = "in_domain" if site in trained_on else "unseen_site"
        conditions = {"raw": None}
        if site in norm:
            conditions["site_normalized"] = {site: norm[site]}
        entry = {"role": role, "site": site, "conditions": {}}
        preds = {}
        for cond, sn in conditions.items():
            rows = predict(model, samples, device, prep, batch, workers, site_norm=sn, seg_stats=site == "her2_ihc_40x" and cond == "raw", amp_dtype=amp)
            preds[cond] = rows
            m = score_metrics([r["label"] for r in rows], [r["pred"] for r in rows])
            c = {"metrics": m}
            if site == "her2_ihc_40x":
                c["metrics_vs_slide_label"] = score_metrics([r["slide_label"] for r in rows], [r["pred"] for r in rows])
                agree = [r["seg_pixel_agreement"] for r in rows if r.get("seg_pixel_agreement") is not None]
                if agree:
                    c["seg_pixel_agreement_with_pseudo_labels"] = float(sum(agree) / len(agree))
            if subset:
                sub = [r for r in rows if Path(r["path"]).name in subset]
                if sub:
                    c["metrics_subset338"] = score_metrics([r["label"] for r in sub], [r["pred"] for r in sub])
            t = targets.get(role)
            if t:
                c["meets_target"] = meets_targets(m, float(t["accuracy"]), float(t["qwk"]))
            entry["conditions"][cond] = c
            for r in rows:
                all_rows.append({"set": name, "condition": cond, **{k: r[k] for k in ("path", "label", "slide_label", "pred", "expected")},
                                 "probs": " ".join(map(str, r["probs"]))})
            log(f"{name} [{role}] {cond}: acc {m['accuracy']:.4f} bal {m['balanced_accuracy']:.4f} "
                f"QWK {m['qwk']:.4f} (n={m['n']})" + (f" | target met: {c.get('meets_target')}" if t else ""))
        if "site_normalized" in preds:
            y = [r["label"] for r in preds["raw"]]
            entry["site_norm_vs_raw"] = paired_bootstrap(y, [r["pred"] for r in preds["raw"]], [r["pred"] for r in preds["site_normalized"]])
        results["sets"][name] = entry

    (out_dir / "eval.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    with (out_dir / "predictions.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        w.writeheader()
        w.writerows(all_rows)
    lines = [f"# {cfg['run_name']}: evaluation", "", f"Trained on: {', '.join(sorted(trained_on))}", "",
             "| Set | Role | Condition | n | Accuracy | Balanced | Macro-F1 | QWK | Target met |", "|---|---|---|---|---|---|---|---|---|"]
    for name, e in results["sets"].items():
        for cond, c in e["conditions"].items():
            m = c["metrics"]
            lines.append(f"| {name} | {e['role']} | {cond} | {m['n']} | {m['accuracy']:.3f} | {m['balanced_accuracy']:.3f} | "
                         f"{m['macro_f1']:.3f} | {m['qwk']:.3f} | {c.get('meets_target', '-')} |")
    (out_dir / "eval_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True)
    parser.add_argument("--checkpoint")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "scripts"))
    from train_v2 import load_config

    cfg = load_config(args.config)
    out_dir = ROOT / "artifacts" / "v2" / cfg["run_name"]
    evaluate_run(cfg, out_dir, Path(args.checkpoint) if args.checkpoint else None)


if __name__ == "__main__":
    main()
