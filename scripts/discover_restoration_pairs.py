#!/usr/bin/env python3
"""Discover noisy/clean audio pairs for restoration experiments."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from radcast.experiments.paired_restoration import discover_pairs, write_pairs_jsonl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover likely noisy/clean lecture audio pairs.")
    parser.add_argument("--noisy-dir", type=Path, action="append", required=True, help="Directory containing original/noisy audio")
    parser.add_argument("--clean-dir", type=Path, action="append", required=True, help="Directory containing cleaned/target audio")
    parser.add_argument("--output-jsonl", type=Path, required=True, help="Output JSONL manifest path")
    parser.add_argument(
        "--suffix",
        action="append",
        default=[".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"],
        help="Allowed file suffix. Repeat to add more.",
    )
    return parser


def _iter_audio_files(root: Path, allowed_suffixes: set[str]) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in allowed_suffixes:
            files.append(path)
    return files


def main() -> None:
    args = build_parser().parse_args()
    allowed_suffixes = {suffix.casefold() if suffix.startswith(".") else f".{suffix.casefold()}" for suffix in args.suffix}
    noisy_files: list[Path] = []
    clean_files: list[Path] = []
    for root in args.noisy_dir:
        noisy_files.extend(_iter_audio_files(root.expanduser().resolve(), allowed_suffixes))
    for root in args.clean_dir:
        clean_files.extend(_iter_audio_files(root.expanduser().resolve(), allowed_suffixes))
    pairs = discover_pairs(noisy_files=noisy_files, clean_files=clean_files)
    write_pairs_jsonl(pairs, args.output_jsonl.expanduser().resolve())
    print(f"Wrote {len(pairs)} discovered pairs to {args.output_jsonl}")


if __name__ == "__main__":
    main()
