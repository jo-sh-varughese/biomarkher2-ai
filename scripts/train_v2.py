"""Train the multi-task U-Net (segmentation + HER2 score head).

    python scripts/train_v2.py --config configs/v2_run_a.yaml [--eval]

The plan, targets and protocol are in docs/V2_TRAINING_PLAN.md. Outputs go to
``artifacts/v2/<run_name>/``: best.pt, last.pt (resume), history.json,
train.log, train_summary.json, and with ``--eval`` the evaluation too.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from preprocessing.config import PreprocessingConfig  # noqa: E402
from training.v2_data import bci_samples, her2_ihc_40x_samples  # noqa: E402


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(path: str | Path) -> dict:
    """YAML config; a ``base:`` key names a file (same folder) to inherit from."""
    path = Path(path)
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if "base" in cfg:
        cfg = _merge(load_config(path.parent / cfg.pop("base")), cfg)
    cfg.setdefault("run_name", path.stem)
    return cfg


def resolve(cfg: dict, key: str) -> Path:
    p = Path(cfg["data"][key])
    return p if p.is_absolute() else ROOT / p


def build_sets(cfg: dict) -> tuple[list, dict]:
    data = cfg["data"]
    sites = data["train_sites"]
    limit = data.get("limit_per_class")
    val_limit = cfg["train"].get("val_limit_per_class")
    fit, val = [], {}
    if "her2_ihc_40x" in sites:
        fit += her2_ihc_40x_samples(resolve(cfg, "her2_root"), resolve(cfg, "her2_split"), "fit", limit, cfg.get("seed", 0))
        val["her2_ihc_40x_val"] = her2_ihc_40x_samples(resolve(cfg, "her2_root"), resolve(cfg, "her2_split"), "val", val_limit, cfg.get("seed", 0))
    if "bci" in sites:
        fit += bci_samples(resolve(cfg, "bci_root"), "fit", limit_per_class=limit)
        val["bci_val"] = bci_samples(resolve(cfg, "bci_root"), "val", limit_per_class=val_limit)
    if not fit:
        raise SystemExit(f"No training samples for train_sites={sites}")
    return fit, val


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True)
    parser.add_argument("--eval", action="store_true", help="run scripts/eval_v2.py on best.pt afterwards")
    args = parser.parse_args()

    from training.v2_engine import train

    cfg = load_config(args.config)
    out_dir = ROOT / "artifacts" / "v2" / cfg["run_name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    log_file = (out_dir / "train.log").open("a", encoding="utf-8")

    def log(msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        log_file.write(line + "\n")
        log_file.flush()

    prep = PreprocessingConfig.from_yaml(ROOT / "configs" / "preprocessing.yaml")
    fit, val = build_sets(cfg)
    log(f"run {cfg['run_name']}: {len(fit)} fit samples, val {{{', '.join(f'{k}: {len(v)}' for k, v in val.items())}}}")
    (out_dir / "resolved_config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    summary = train(cfg, fit, val, out_dir, prep, log=log)
    log(f"training done: {json.dumps(summary)}")
    if args.eval:
        from scripts.eval_v2 import evaluate_run

        evaluate_run(cfg, out_dir, log=log)


if __name__ == "__main__":
    main()
