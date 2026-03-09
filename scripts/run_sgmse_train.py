#!/usr/bin/env python3
"""Run official SGMSE training from a RADcast paired dataset."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch official SGMSE training on a RADcast paired dataset.")
    parser.add_argument("--sgmse-dir", type=Path, required=True, help="Path to a local checkout of the official SGMSE repo")
    parser.add_argument("--dataset-dir", type=Path, required=True, help="Path to the paired dataset base dir")
    parser.add_argument("--log-dir", type=Path, required=True, help="Directory where SGMSE should write logs/checkpoints")
    parser.add_argument("--python", default="python", help="Python executable for the SGMSE environment")
    parser.add_argument("--wandb-name", default="radcast-restoration", help="Run name for SGMSE logging")
    parser.add_argument("--backbone", default="ncsnpp_48k")
    parser.add_argument("--n-fft", type=int, default=1534)
    parser.add_argument("--hop-length", type=int, default=384)
    parser.add_argument("--spec-factor", type=float, default=0.065)
    parser.add_argument("--spec-abs-exponent", type=float, default=0.667)
    parser.add_argument("--sigma-min", type=float, default=0.1)
    parser.add_argument("--sigma-max", type=float, default=1.0)
    parser.add_argument("--theta", type=float, default=2.0)
    parser.add_argument("--smoke", action="store_true", help="Run a cheap one-epoch dummy training smoke test")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("extra_args", nargs="*", help="Additional args passed through to train.py")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    train_py = args.sgmse_dir.expanduser().resolve() / "train.py"
    if not train_py.exists():
        raise SystemExit(f"Could not find {train_py}")
    dataset_dir = args.dataset_dir.expanduser().resolve()
    if not dataset_dir.exists():
        raise SystemExit(f"Could not find dataset dir {dataset_dir}")

    command = [
        args.python,
        str(train_py),
        "--base_dir",
        str(dataset_dir),
        "--log_dir",
        str(args.log_dir.expanduser().resolve()),
        "--wandb_name",
        args.wandb_name,
        "--backbone",
        args.backbone,
        "--n_fft",
        str(args.n_fft),
        "--hop_length",
        str(args.hop_length),
        "--spec_factor",
        str(args.spec_factor),
        "--spec_abs_exponent",
        str(args.spec_abs_exponent),
        "--sigma-min",
        str(args.sigma_min),
        "--sigma-max",
        str(args.sigma_max),
        "--theta",
        str(args.theta),
    ]

    if args.smoke:
        # Keep the first run cheap but real enough to exercise dataloading and optimization.
        command.extend(
            [
                "--accelerator",
                "cpu",
                "--devices",
                "1",
                "--max_epochs",
                "1",
                "--batch_size",
                "1",
                "--num_workers",
                "0",
                "--dummy",
                "--nolog",
                "--num_eval_files",
                "0",
            ]
        )

    command.extend(args.extra_args)

    print(" ".join(command))
    if args.dry_run:
        return

    subprocess.run(command, check=True, cwd=str(args.sgmse_dir.expanduser().resolve()))


if __name__ == "__main__":
    main()
