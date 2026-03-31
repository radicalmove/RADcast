#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for filename in files:
            candidate = Path(root) / filename
            try:
                total += candidate.stat().st_size
            except OSError:
                continue
    return total


def path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return dir_size(path)
    raise FileNotFoundError(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a transfer manifest for the dedicated GPU restoration box.")
    parser.add_argument("--radcast-root", type=Path, required=True)
    parser.add_argument("--sgmse-root", type=Path, required=True)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument(
        "--checkpoint",
        action="append",
        default=[],
        help="Checkpoint in the form NAME=/abs/path/to/file.ckpt. Can be repeated.",
    )
    parser.add_argument("--output-json", type=Path, help="Optional JSON output path.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    entries: list[dict[str, object]] = []

    roots = [
        ("radcast_root", args.radcast_root.expanduser().resolve()),
        ("sgmse_root", args.sgmse_root.expanduser().resolve()),
        ("dataset_dir", args.dataset_dir.expanduser().resolve()),
    ]
    for label, path in roots:
        entries.append(
            {
                "label": label,
                "path": str(path),
                "size_bytes": path_size(path),
            }
        )

    for raw in args.checkpoint:
        if "=" not in raw:
            raise SystemExit(f"invalid checkpoint '{raw}', expected NAME=PATH")
        label, raw_path = raw.split("=", 1)
        path = Path(raw_path).expanduser().resolve()
        entries.append(
            {
                "label": f"checkpoint:{label}",
                "path": str(path),
                "size_bytes": path_size(path),
            }
        )

    payload = {
        "entries": entries,
        "total_size_bytes": sum(int(entry["size_bytes"]) for entry in entries),
    }

    if args.output_json:
        output_path = args.output_json.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
