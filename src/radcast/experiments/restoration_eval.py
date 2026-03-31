from __future__ import annotations

import json
import math
from pathlib import Path


WEIGHTS: dict[str, float] = {
    "centroid_hz": 1 / 400.0,
    "band_0_250_db": 1.0,
    "band_250_700_db": 1.3,
    "band_700_2000_db": 1.5,
    "band_2000_4500_db": 2.0,
    "band_4500_8000_db": 2.0,
    "rms_db": 0.6,
}

KEYS: tuple[str, ...] = tuple(WEIGHTS)


def parse_report_text(text: str) -> dict[str, dict[str, float]]:
    blocks: dict[str, dict[str, float]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line and not line.startswith(" ") and ":" not in line:
            current = line.strip()
            blocks[current] = {}
        elif current and line.startswith("  "):
            key, value = line.strip().split(": ", 1)
            blocks[current][key] = float(value)
    return blocks


def parse_report_file(path: Path) -> dict[str, dict[str, float]]:
    return parse_report_text(path.read_text(encoding="utf-8"))


def score_blocks(
    blocks: dict[str, dict[str, float]],
    ref: str = "adobe",
    target: str = "restored",
) -> tuple[float, dict[str, float]]:
    total = 0.0
    diffs: dict[str, float] = {}
    for key in KEYS:
        diff = blocks[target][key] - blocks[ref][key]
        diffs[key] = diff
        total += (diff * WEIGHTS[key]) ** 2
    return math.sqrt(total), diffs


def score_report_file(
    path: Path,
    ref: str = "adobe",
    target: str = "restored",
) -> dict[str, object]:
    blocks = parse_report_file(path)
    score, diffs = score_blocks(blocks, ref=ref, target=target)
    return {"score": score, "diffs": diffs}


def write_score_json(
    report_path: Path,
    output_path: Path,
    ref: str = "adobe",
    target: str = "restored",
) -> dict[str, object]:
    payload = score_report_file(report_path, ref=ref, target=target)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload
