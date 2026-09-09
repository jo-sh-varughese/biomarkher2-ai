"""Run Phase 2 training.

    python scripts/train_phase2.py --config configs/training.yaml

Requires the pseudo-label cache to exist -- run scripts/build_pseudo_labels.py
first, and look at the preview montage it writes before training on it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.config import TrainingConfig
from training.train import train


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/training.yaml")
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--max-fit-patches", type=int, default=None)
    parser.add_argument("--max-val-patches", type=int, default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument(
        "--threads",
        type=int,
        default=None,
        help="torch CPU threads. Defaults to whatever torch picks.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Continue from <output-dir>/resume.pt if present, rather than "
        "starting over. See training/train.py's module docstring, "
        "'RESUMING AN INTERRUPTED RUN' -- written for exactly the situation "
        "a multi-hour CPU run getting killed partway through leaves behind.",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=20,
        help="Write the resume checkpoint every N fit batches (default 20). "
        "Lower it on a machine that gets interrupted often -- more frequent "
        "checkpoints cost more disk I/O but bound how much work a kill can "
        "cost to at most this many batches.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = (
        TrainingConfig.from_yaml(args.config)
        if Path(args.config).is_file()
        else TrainingConfig()
    )
    # Command-line overrides exist for smoke runs; each one is echoed into
    # resolved_config.yaml by train(), so what ran is always recoverable.
    if args.epochs is not None:
        config.optim.epochs = args.epochs
    if args.max_fit_patches is not None:
        config.data.max_fit_patches = args.max_fit_patches
    if args.max_val_patches is not None:
        config.data.max_val_patches = args.max_val_patches
    if args.output_dir is not None:
        config.output_dir = args.output_dir
    if args.threads is not None:
        torch.set_num_threads(args.threads)

    train(config, resume=args.resume, checkpoint_every=args.checkpoint_every)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
