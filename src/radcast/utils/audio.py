"""Audio process helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_ffmpeg_convert(src: Path, dst: Path, *, audio_filters: str | None = None) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
    ]
    if audio_filters and audio_filters.strip():
        cmd.extend(["-af", audio_filters.strip()])
    cmd.append(str(dst))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "ffmpeg failed").strip()
        raise RuntimeError(message)


def run_ffmpeg_trim(
    src: Path,
    dst: Path,
    *,
    clip_start_seconds: float | None = None,
    clip_end_seconds: float | None = None,
    audio_filters: str | None = None,
) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
    ]
    if clip_start_seconds is not None:
        cmd.extend(["-ss", f"{max(0.0, float(clip_start_seconds)):.3f}"])
    if clip_end_seconds is not None:
        cmd.extend(["-to", f"{max(0.0, float(clip_end_seconds)):.3f}"])
    if audio_filters and audio_filters.strip():
        cmd.extend(["-af", audio_filters.strip()])
    cmd.append(str(dst))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "ffmpeg failed").strip()
        raise RuntimeError(message)


def run_ffmpeg_excerpt(
    src: Path,
    dst: Path,
    *,
    clip_start_seconds: float,
    clip_end_seconds: float,
    padding_seconds: float = 0.35,
) -> None:
    safe_padding = max(0.0, float(padding_seconds))
    safe_start = max(0.0, float(clip_start_seconds) - safe_padding)
    safe_end = max(safe_start + 0.2, float(clip_end_seconds) + safe_padding)
    run_ffmpeg_trim(
        src,
        dst,
        clip_start_seconds=safe_start,
        clip_end_seconds=safe_end,
    )


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
