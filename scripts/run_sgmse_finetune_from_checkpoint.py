#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fine-tune an SGMSE checkpoint with fresh optimizer state and overridden hyperparameters."
    )
    parser.add_argument("--sgmse-dir", type=Path, required=True)
    parser.add_argument("--base-checkpoint", type=Path, required=True)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--python", default="python")
    parser.add_argument("--accelerator", default="cuda")
    parser.add_argument("--devices", default="1")
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--num-workers", type=int, default=6)
    parser.add_argument("--max-epochs", type=int, default=2)
    parser.add_argument("--check-val-every-n-epoch", type=int, default=1)
    parser.add_argument("--limit-train-batches", type=float, default=0.25)
    parser.add_argument("--limit-val-batches", type=float, default=0.25)
    parser.add_argument("--save-ckpt-interval", type=int, default=100)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--l1-weight", type=float, default=0.005)
    parser.add_argument("--num-eval-files", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("extra_args", nargs="*")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    sgmse_dir = args.sgmse_dir.expanduser().resolve()
    ckpt = args.base_checkpoint.expanduser().resolve()
    dataset = args.dataset_dir.expanduser().resolve()
    log_dir = args.log_dir.expanduser().resolve()

    if not (sgmse_dir / "sgmse").exists():
        raise SystemExit(f"Missing SGMSE package under {sgmse_dir}")
    if not ckpt.exists():
        raise SystemExit(f"Missing checkpoint {ckpt}")
    if not dataset.exists():
        raise SystemExit(f"Missing dataset {dataset}")

    log_dir.mkdir(parents=True, exist_ok=True)

    script = f"""
import sys
from pathlib import Path

import pytorch_lightning as pl
from pytorch_lightning.callbacks import ModelCheckpoint
from torch.serialization import add_safe_globals

sys.path.insert(0, r"{sgmse_dir}")

from sgmse.data_module import SpecsDataModule
from sgmse.model import ScoreModel

add_safe_globals([SpecsDataModule])

model = ScoreModel.load_from_checkpoint(
    r"{ckpt}",
    map_location="cpu",
    base_dir=r"{dataset}",
    batch_size={args.batch_size},
    num_workers={args.num_workers},
    num_eval_files={args.num_eval_files},
    lr={args.lr},
    l1_weight={args.l1_weight},
)

callbacks = [
    ModelCheckpoint(dirpath=r"{log_dir}", save_last=True, filename="last"),
    ModelCheckpoint(dirpath=r"{log_dir}", filename="step={{step}}", save_top_k=-1, every_n_train_steps={args.save_ckpt_interval}),
]

trainer = pl.Trainer(
    accelerator=r"{args.accelerator}",
    devices={int(args.devices) if str(args.devices).isdigit() else repr(args.devices)},
    strategy="auto",
    logger=None,
    log_every_n_steps=10,
    num_sanity_val_steps=0,
    callbacks=callbacks,
    max_epochs={args.max_epochs},
    check_val_every_n_epoch={args.check_val_every_n_epoch},
    limit_train_batches={args.limit_train_batches},
    limit_val_batches={args.limit_val_batches},
)

trainer.fit(model)
"""

    command = [args.python, "-c", script, *args.extra_args]
    print(" ".join(command[:2]), "...")
    if args.dry_run:
        return

    subprocess.run(command, cwd=str(sgmse_dir), env=os.environ.copy(), check=True)


if __name__ == "__main__":
    main()
