"""Audio process helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_ffmpeg_convert(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "ffmpeg failed").strip()
        raise RuntimeError(message)


def probe_duration_seconds(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "ffprobe failed").strip()
        raise RuntimeError(message)
    raw = (result.stdout or "").strip()
    if not raw:
        raise RuntimeError("ffprobe returned empty duration")
    return float(raw)
