#!/usr/bin/env python3
"""Build a paired noisy/clean dataset for RADcast restoration experiments."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from radcast.experiments.paired_restoration import (
    build_paired_dataset,
    load_pairs_jsonl,
    parse_pair_argument,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a train/valid noisy-clean dataset for speech-restoration experiments."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--pair",
        action="append",
        help="Pair in the form /path/to/noisy::/path/to/clean. Repeat for multiple pairs.",
    )
    source.add_argument(
        "--pairs-jsonl",
        type=Path,
        help="JSONL file with noisy_path, clean_path, and optional pair_id fields.",
    )
    parser.add_argument("--output-dir", type=Path, required=True, help="Dataset output folder")
    parser.add_argument("--sample-rate", type=int, default=48_000)
    parser.add_argument("--segment-seconds", type=float, default=8.0)
    parser.add_argument("--hop-seconds", type=float, default=4.0)
    parser.add_argument("--activity-threshold-db", type=float, default=-38.0)
    parser.add_argument("--min-active-ratio", type=float, default=0.30)
    parser.add_argument("--valid-fraction", type=float, default=0.2)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.pairs_jsonl:
        pairs = load_pairs_jsonl(args.pairs_jsonl.expanduser().resolve())
    else:
        pairs = [parse_pair_argument(raw) for raw in (args.pair or [])]

    records = build_paired_dataset(
        pairs=pairs,
        output_dir=args.output_dir.expanduser().resolve(),
        sample_rate=args.sample_rate,
        segment_seconds=args.segment_seconds,
        hop_seconds=args.hop_seconds,
        activity_threshold_db=args.activity_threshold_db,
        min_active_ratio=args.min_active_ratio,
        valid_fraction=args.valid_fraction,
        overwrite=args.overwrite,
    )
    print(f"Wrote {len(records)} paired segments to {args.output_dir}")


if __name__ == "__main__":
    main()
