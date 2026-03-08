"""Resemble Enhance wrapper service."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from radcast.constants import (
    DEFAULT_ENHANCE_COMMAND,
    DEFAULT_ENHANCE_DEVICE,
    DEFAULT_ENHANCE_LAMBD,
    DEFAULT_ENHANCE_NFE,
    DEFAULT_ENHANCE_TAU,
)
from radcast.exceptions import EnhancementRuntimeError, JobCancelledError
from radcast.models import OutputFormat
from radcast.utils.audio import probe_duration_seconds, run_ffmpeg_convert


class EnhanceService:
    def __init__(self) -> None:
        command_raw = os.environ.get("RADCAST_ENHANCE_COMMAND", DEFAULT_ENHANCE_COMMAND).strip()
        self.command = _resolve_command(command_raw)
        self.device = os.environ.get("RADCAST_ENHANCE_DEVICE", DEFAULT_ENHANCE_DEVICE).strip() or DEFAULT_ENHANCE_DEVICE
        self.nfe = _safe_int(os.environ.get("RADCAST_ENHANCE_NFE"), DEFAULT_ENHANCE_NFE)
        self.lambd = _safe_float(os.environ.get("RADCAST_ENHANCE_LAMBD"), DEFAULT_ENHANCE_LAMBD)
        self.tau = _safe_float(os.environ.get("RADCAST_ENHANCE_TAU"), DEFAULT_ENHANCE_TAU)
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.Lock()

    def cancel(self, job_id: str) -> None:
        with self._lock:
            proc = self._processes.get(job_id)
        if proc and proc.poll() is None:
            proc.terminate()

    def enhance(
        self,
        *,
        job_id: str,
        input_audio_path: Path,
        output_format: OutputFormat,
        output_base_path: Path,
        on_stage: Callable[[str, float, str, int | None], None],
        cancel_check: Callable[[], bool],
    ) -> Path:
        if cancel_check():
            raise JobCancelledError("job cancelled")

        with tempfile.TemporaryDirectory(prefix=f"radcast_{job_id}_") as tmp:
            tmp_path = Path(tmp)
            in_dir = tmp_path / "in"
            out_dir = tmp_path / "out"
            in_dir.mkdir(parents=True, exist_ok=True)
            out_dir.mkdir(parents=True, exist_ok=True)

            on_stage("prepare", 0.12, "Preparing source audio")
            in_wav = in_dir / "input.wav"
            if input_audio_path.suffix.lower() == ".wav":
                in_wav.write_bytes(input_audio_path.read_bytes())
            else:
                run_ffmpeg_convert(input_audio_path, in_wav)
            input_duration_seconds = probe_duration_seconds(in_wav)

            if cancel_check():
                raise JobCancelledError("job cancelled")

            cmd = [
                *self.command,
                str(in_dir),
                str(out_dir),
                "--suffix",
                ".wav",
                "--device",
                self.device,
                "--nfe",
                str(self.nfe),
                "--lambd",
                str(self.lambd),
                "--tau",
                str(self.tau),
            ]

            expected_runtime_seconds = _estimate_runtime_seconds(
                input_duration_seconds,
                device=self.device,
                nfe=self.nfe,
            )
            on_stage(
                "enhance",
                0.2,
                "Loading the enhancement engine. First run on a server can take longer.",
                None,
            )
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            except FileNotFoundError as exc:
                raise EnhancementRuntimeError(
                    "Enhancement command not found. Install Resemble Enhance or set RADCAST_ENHANCE_COMMAND."
                ) from exc

            with self._lock:
                self._processes[job_id] = proc

            started = time.monotonic()
            try:
                while proc.poll() is None:
                    if cancel_check():
                        proc.terminate()
                        raise JobCancelledError("job cancelled")
                    elapsed = time.monotonic() - started
                    progress = _estimate_progress(elapsed, expected_runtime_seconds)
                    eta_seconds = _estimate_remaining_seconds(elapsed, expected_runtime_seconds)
                    if elapsed < min(10.0, expected_runtime_seconds * 0.18):
                        detail = "Loading the enhancement engine. First run on a server can take longer."
                    elif eta_seconds is None:
                        detail = "Improving audio quality. Finishing soon."
                    else:
                        detail = "Improving audio quality."
                    on_stage("enhance", progress, detail, eta_seconds)
                    time.sleep(0.6)

                stdout, stderr = proc.communicate()
                if proc.returncode != 0:
                    msg = (stderr or stdout or "Enhancement process failed").strip()
                    raise EnhancementRuntimeError(msg[-2000:])
            finally:
                with self._lock:
                    self._processes.pop(job_id, None)

            if cancel_check():
                raise JobCancelledError("job cancelled")

            out_candidates = sorted(out_dir.glob("**/*.wav"))
            if not out_candidates:
                raise EnhancementRuntimeError("Enhancement did not produce output audio")
            enhanced_wav = out_candidates[0]

            on_stage("finalize", 0.96, "Saving the enhanced audio", 8)
            output_base_path.parent.mkdir(parents=True, exist_ok=True)

            if output_format == OutputFormat.WAV:
                final_path = output_base_path.with_suffix(".wav")
                final_path.write_bytes(enhanced_wav.read_bytes())
                return final_path

            final_path = output_base_path.with_suffix(".mp3")
            run_ffmpeg_convert(enhanced_wav, final_path)
            return final_path


def _safe_int(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _safe_float(raw: str | None, default: float) -> float:
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _resolve_command(command_raw: str) -> list[str]:
    raw = command_raw or DEFAULT_ENHANCE_COMMAND
    parts = shlex.split(raw) if raw else [DEFAULT_ENHANCE_COMMAND]
    executable = parts[0]

    if "/" in executable:
        return parts

    venv_candidate = Path(sys.executable).resolve().with_name(executable)
    if venv_candidate.exists():
        parts[0] = str(venv_candidate)
        return parts

    system_candidate = shutil.which(executable)
    if system_candidate:
        parts[0] = system_candidate

    return parts


def _estimate_runtime_seconds(duration_seconds: float, *, device: str, nfe: int) -> int:
    safe_duration = max(1.0, float(duration_seconds))
    quality_factor = max(0.65, float(nfe) / float(DEFAULT_ENHANCE_NFE))
    normalized_device = (device or DEFAULT_ENHANCE_DEVICE).strip().lower()

    if normalized_device.startswith("cuda") or normalized_device == "mps":
        base_seconds = 12.0
        per_second = 1.8
        minimum = 18
    else:
        base_seconds = 32.0
        per_second = 4.2
        minimum = 35

    estimate = (base_seconds + (safe_duration * per_second)) * quality_factor
    return max(minimum, min(int(round(estimate)), 30 * 60))


def _estimate_progress(elapsed_seconds: float, expected_runtime_seconds: int) -> float:
    expected = max(1.0, float(expected_runtime_seconds))
    ratio = max(0.0, elapsed_seconds / expected)

    if ratio <= 1.0:
        eased = ratio ** 0.92
        return min(0.88, 0.2 + (0.66 * eased))

    overtime_ratio = min(1.0, (ratio - 1.0) / 0.75)
    return min(0.94, 0.86 + (0.08 * overtime_ratio))


def _estimate_remaining_seconds(elapsed_seconds: float, expected_runtime_seconds: int) -> int | None:
    if elapsed_seconds < 8.0:
        return None

    remaining = int(round(expected_runtime_seconds - elapsed_seconds))
    if remaining <= 0:
        return None
    return remaining
