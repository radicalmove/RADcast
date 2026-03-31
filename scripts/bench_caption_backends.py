#!/usr/bin/env python3
"""Benchmark RADcast caption backends with structured stage timing output."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from radcast.models import CaptionFormat, CaptionQualityMode
from radcast.services.speech_cleanup import SpeechCleanupService
from radcast.utils.audio import probe_duration_seconds

_WINDOW_DETAIL_RE = re.compile(r"\bWindow\s+(\d+)\s+of\s+(\d+)\b", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True, help="Path to the input audio file.")
    parser.add_argument(
        "--backend",
        default="auto",
        choices=("auto", "faster_whisper", "whispercpp"),
        help="Caption backend to request.",
    )
    parser.add_argument(
        "--quality",
        default="reviewed",
        choices=tuple(mode.value for mode in CaptionQualityMode),
        help="Caption quality mode to benchmark.",
    )
    parser.add_argument(
        "--runtime-context",
        default="local_helper",
        choices=("local_helper", "server"),
        help="Runtime context passed into backend selection.",
    )
    parser.add_argument(
        "--caption-format",
        default="vtt",
        choices=tuple(fmt.value for fmt in CaptionFormat),
        help="Caption format used for the benchmark run.",
    )
    parser.add_argument("--glossary", default=None, help="Optional glossary prompt additions.")
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Keep generated caption artifacts in a temp benchmark directory.",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help="Optional path to write the benchmark JSON report.",
    )
    return parser.parse_args()


@contextmanager
def temporary_env(overrides: dict[str, str]):
    original = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            os.environ[key] = value
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def summarize_events(events: list[dict[str, object]], *, total_wall_clock_seconds: float) -> dict[str, object]:
    seen_windows: set[int] = set()
    window_starts: list[tuple[int, float]] = []
    review_start: float | None = None
    write_start: float | None = None

    for event in events:
        detail = str(event.get("detail") or "")
        elapsed = float(event.get("elapsed_seconds") or 0.0)
        match = _WINDOW_DETAIL_RE.search(detail)
        if match:
            window_number = int(match.group(1))
            if window_number not in seen_windows:
                seen_windows.add(window_number)
                window_starts.append((window_number, elapsed))
            continue
        if review_start is None and detail.startswith("Reviewing low-confidence caption lines."):
            review_start = elapsed
        if write_start is None and detail.startswith("Writing "):
            write_start = elapsed

    first_pass_end = review_start if review_start is not None else write_start if write_start is not None else total_wall_clock_seconds
    first_window_latency_seconds: float | None = None
    median_window_latency_seconds: float | None = None
    first_pass_runtime_seconds: float | None = None

    if window_starts:
        first_window_start = window_starts[0][1]
        first_window_latency_seconds = max(0.0, (window_starts[1][1] if len(window_starts) > 1 else first_pass_end) - first_window_start)
        first_pass_runtime_seconds = max(0.0, first_pass_end - first_window_start)

        window_latencies = [
            max(0.0, window_starts[index + 1][1] - window_starts[index][1])
            for index in range(len(window_starts) - 1)
        ]
        window_latencies.append(max(0.0, first_pass_end - window_starts[-1][1]))
        if window_latencies:
            median_window_latency_seconds = statistics.median(window_latencies)

    review_runtime_seconds: float | None = None
    if review_start is not None:
        review_end = write_start if write_start is not None else total_wall_clock_seconds
        review_runtime_seconds = max(0.0, review_end - review_start)

    return {
        "observed_window_count": len(window_starts),
        "first_window_latency_seconds": first_window_latency_seconds,
        "median_window_latency_seconds": median_window_latency_seconds,
        "first_pass_runtime_seconds": first_pass_runtime_seconds,
        "review_runtime_seconds": review_runtime_seconds,
    }


def main() -> int:
    args = parse_args()
    audio_path = Path(args.audio).expanduser().resolve()
    if not audio_path.exists():
        raise SystemExit(f"Audio file not found: {audio_path}")

    env_overrides = {
        "RADCAST_CAPTION_BACKEND": args.backend,
        "RADCAST_RUNTIME_CONTEXT": args.runtime_context,
    }
    quality_mode = CaptionQualityMode(args.quality)
    caption_format = CaptionFormat(args.caption_format)

    with temporary_env(env_overrides):
        service = SpeechCleanupService()
        events: list[dict[str, object]] = []

        def on_stage(progress: float, detail: str, eta_seconds: int | None) -> None:
            events.append(
                {
                    "elapsed_seconds": round(time.monotonic() - started_at, 3),
                    "progress": round(float(progress), 4),
                    "detail": detail,
                    "eta_seconds": eta_seconds,
                }
            )

        benchmark_root_cm = tempfile.TemporaryDirectory(prefix="radcast_caption_bench_")
        benchmark_root = Path(benchmark_root_cm.name)
        try:
            working_audio = benchmark_root / audio_path.name
            shutil.copy2(audio_path, working_audio)

            started_at = time.monotonic()
            result = service.generate_caption_file(
                audio_path=working_audio,
                caption_format=caption_format,
                caption_quality_mode=quality_mode,
                caption_glossary=args.glossary,
                on_stage=on_stage,
            )
            total_wall_clock_seconds = time.monotonic() - started_at

            report = {
                "audio_path": str(audio_path),
                "audio_duration_seconds": round(probe_duration_seconds(audio_path), 3),
                "requested_backend": args.backend,
                "resolved_backend": service.caption_backend_id,
                "quality_mode": quality_mode.value,
                "runtime_context": args.runtime_context,
                "caption_format": caption_format.value,
                "total_wall_clock_seconds": round(total_wall_clock_seconds, 3),
                "timings": summarize_events(events, total_wall_clock_seconds=total_wall_clock_seconds),
                "events": events,
                "artifacts": {
                    "caption_path": str(result.caption_path) if args.keep_artifacts else None,
                    "review_path": str(result.review_path) if (args.keep_artifacts and result.review_path is not None) else None,
                    "kept": bool(args.keep_artifacts),
                    "benchmark_root": str(benchmark_root) if args.keep_artifacts else None,
                },
            }
            if args.output_json:
                output_path = Path(args.output_json).expanduser().resolve()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
        finally:
            if not args.keep_artifacts:
                benchmark_root_cm.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
