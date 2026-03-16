"""Audio enhancement service with pluggable backend models."""

from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from importlib.util import find_spec
from pathlib import Path
from typing import Callable

from radcast.constants import (
    DEFAULT_AUDIO_TUNING_LABEL,
    DEFAULT_DEEPFILTERNET_COMMAND,
    DEFAULT_DEEPFILTERNET_MODEL,
    DEFAULT_DEEPFILTERNET_POST_FILTER,
    DEFAULT_ENHANCE_COMMAND,
    DEFAULT_ENHANCE_DEVICE,
    DEFAULT_ENHANCE_LAMBD,
    DEFAULT_ENHANCE_NFE,
    DEFAULT_ENHANCE_PREFILTER,
    DEFAULT_ENHANCE_POSTFILTER,
    DEFAULT_ENHANCE_TAU,
    DEFAULT_ENHANCEMENT_MODEL,
    DEFAULT_STUDIO_POSTFILTER,
    DEFAULT_STUDIO_COMMAND,
    DEFAULT_STUDIO_V18_DEREVERB_METHOD,
    DEFAULT_STUDIO_V18_LAMBD,
    DEFAULT_STUDIO_V18_NFE,
    DEFAULT_STUDIO_V18_NARA_CHUNK_SECONDS,
    DEFAULT_STUDIO_V18_NARA_DELAY,
    DEFAULT_STUDIO_V18_NARA_ITERATIONS,
    DEFAULT_STUDIO_V18_NARA_OVERLAP_SECONDS,
    DEFAULT_STUDIO_V18_NARA_PSD_CONTEXT,
    DEFAULT_STUDIO_V18_NARA_TAPS,
    DEFAULT_STUDIO_V18_POSTFILTER,
    DEFAULT_STUDIO_V18_PREFILTER,
    DEFAULT_STUDIO_V18_TAU,
    DEFAULT_STUDIO_V18_TUNING_LABEL,
    DEFAULT_STUDIO_V18_WPE_DELAY,
    DEFAULT_STUDIO_V18_WPE_ITERATIONS,
    DEFAULT_STUDIO_V18_WPE_TAPS,
)
from radcast.exceptions import EnhancementRuntimeError, JobCancelledError
from radcast.models import EnhancementModel, OutputFormat
from radcast.utils.audio import probe_duration_seconds, run_ffmpeg_convert

MODEL_LABELS = {
    EnhancementModel.NONE: "Do not enhance",
    EnhancementModel.RESEMBLE: "Resemble Enhance",
    EnhancementModel.DEEPFILTERNET: "DeepFilterNet3",
    EnhancementModel.STUDIO: "Studio Cleanup",
    EnhancementModel.STUDIO_V18: "RADcast Optimized",
}

MODEL_DESCRIPTIONS = {
    EnhancementModel.NONE: "Keeps the original audio quality and only applies optional silence or filler cleanup.",
    EnhancementModel.RESEMBLE: "Current RADcast backend. Strong cleanup, but can sound more processed.",
    EnhancementModel.DEEPFILTERNET: "Official DeepFilterNet3 speech enhancement. Usually more natural and less compressed.",
    EnhancementModel.STUDIO: "Custom late-reverb suppression plus Resemble Enhance. Built to chase a drier studio-mic sound.",
    EnhancementModel.STUDIO_V18: "Default RADcast cleanup. Chunked dereverb plus lighter restoration tuned toward a close-mic lecture sound.",
}


def current_audio_tuning_label(model: EnhancementModel | None = None) -> str | None:
    if model == EnhancementModel.NONE:
        return None
    if model == EnhancementModel.STUDIO_V18:
        raw = str(os.environ.get("RADCAST_STUDIO_V18_TUNING_LABEL", DEFAULT_STUDIO_V18_TUNING_LABEL)).strip()
        return raw or DEFAULT_STUDIO_V18_TUNING_LABEL
    raw = str(os.environ.get("RADCAST_AUDIO_TUNING_LABEL", DEFAULT_AUDIO_TUNING_LABEL)).strip()
    return raw or DEFAULT_AUDIO_TUNING_LABEL


class EnhanceService:
    def __init__(self) -> None:
        self.default_model = _parse_model(os.environ.get("RADCAST_DEFAULT_ENHANCEMENT_MODEL"), DEFAULT_ENHANCEMENT_MODEL)
        self.resemble_command = _resolve_command(os.environ.get("RADCAST_ENHANCE_COMMAND", DEFAULT_ENHANCE_COMMAND).strip())
        self.studio_command = _resolve_command(os.environ.get("RADCAST_STUDIO_COMMAND", DEFAULT_STUDIO_COMMAND).strip())
        self.deepfilternet_command = _resolve_command(
            os.environ.get("RADCAST_DEEPFILTERNET_COMMAND", DEFAULT_DEEPFILTERNET_COMMAND).strip()
        )
        self.deepfilternet_model = (
            os.environ.get("RADCAST_DEEPFILTERNET_MODEL", DEFAULT_DEEPFILTERNET_MODEL).strip()
            or DEFAULT_DEEPFILTERNET_MODEL
        )
        self.deepfilternet_post_filter = _safe_bool(
            os.environ.get("RADCAST_DEEPFILTERNET_POST_FILTER"),
            DEFAULT_DEEPFILTERNET_POST_FILTER,
        )
        self.device = _resolve_enhance_device(os.environ.get("RADCAST_ENHANCE_DEVICE"))
        self.nfe = _safe_int(os.environ.get("RADCAST_ENHANCE_NFE"), DEFAULT_ENHANCE_NFE)
        self.lambd = _safe_float(os.environ.get("RADCAST_ENHANCE_LAMBD"), DEFAULT_ENHANCE_LAMBD)
        self.tau = _safe_float(os.environ.get("RADCAST_ENHANCE_TAU"), DEFAULT_ENHANCE_TAU)
        self.prefilter = os.environ.get("RADCAST_ENHANCE_PREFILTER", DEFAULT_ENHANCE_PREFILTER).strip()
        self.postfilter = os.environ.get("RADCAST_ENHANCE_POSTFILTER", DEFAULT_ENHANCE_POSTFILTER).strip()
        self.studio_postfilter = os.environ.get("RADCAST_STUDIO_POSTFILTER", DEFAULT_STUDIO_POSTFILTER).strip()
        self.studio_v18_prefilter = os.environ.get("RADCAST_STUDIO_V18_PREFILTER", DEFAULT_STUDIO_V18_PREFILTER).strip()
        self.studio_v18_postfilter = os.environ.get("RADCAST_STUDIO_V18_POSTFILTER", DEFAULT_STUDIO_V18_POSTFILTER).strip()
        self.studio_v18_dereverb_method = (
            os.environ.get("RADCAST_STUDIO_V18_DEREVERB_METHOD", DEFAULT_STUDIO_V18_DEREVERB_METHOD).strip().lower()
            or DEFAULT_STUDIO_V18_DEREVERB_METHOD
        )
        self.studio_v18_nfe = _safe_int(os.environ.get("RADCAST_STUDIO_V18_NFE"), DEFAULT_STUDIO_V18_NFE)
        self.studio_v18_lambd = _safe_float(os.environ.get("RADCAST_STUDIO_V18_LAMBD"), DEFAULT_STUDIO_V18_LAMBD)
        self.studio_v18_tau = _safe_float(os.environ.get("RADCAST_STUDIO_V18_TAU"), DEFAULT_STUDIO_V18_TAU)
        self.studio_v18_wpe_taps = _safe_int(os.environ.get("RADCAST_STUDIO_V18_WPE_TAPS"), DEFAULT_STUDIO_V18_WPE_TAPS)
        self.studio_v18_wpe_delay = _safe_int(os.environ.get("RADCAST_STUDIO_V18_WPE_DELAY"), DEFAULT_STUDIO_V18_WPE_DELAY)
        self.studio_v18_wpe_iterations = _safe_int(
            os.environ.get("RADCAST_STUDIO_V18_WPE_ITERATIONS"),
            DEFAULT_STUDIO_V18_WPE_ITERATIONS,
        )
        self.studio_v18_nara_chunk_seconds = _safe_float(
            os.environ.get("RADCAST_STUDIO_V18_NARA_CHUNK_SECONDS"),
            DEFAULT_STUDIO_V18_NARA_CHUNK_SECONDS,
        )
        self.studio_v18_nara_overlap_seconds = _safe_float(
            os.environ.get("RADCAST_STUDIO_V18_NARA_OVERLAP_SECONDS"),
            DEFAULT_STUDIO_V18_NARA_OVERLAP_SECONDS,
        )
        self.studio_v18_nara_taps = _safe_int(os.environ.get("RADCAST_STUDIO_V18_NARA_TAPS"), DEFAULT_STUDIO_V18_NARA_TAPS)
        self.studio_v18_nara_delay = _safe_int(
            os.environ.get("RADCAST_STUDIO_V18_NARA_DELAY"),
            DEFAULT_STUDIO_V18_NARA_DELAY,
        )
        self.studio_v18_nara_iterations = _safe_int(
            os.environ.get("RADCAST_STUDIO_V18_NARA_ITERATIONS"),
            DEFAULT_STUDIO_V18_NARA_ITERATIONS,
        )
        self.studio_v18_nara_psd_context = _safe_int(
            os.environ.get("RADCAST_STUDIO_V18_NARA_PSD_CONTEXT"),
            DEFAULT_STUDIO_V18_NARA_PSD_CONTEXT,
        )
        self.audio_tuning_label = current_audio_tuning_label()
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.Lock()

    def available_models(self) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        for model in EnhancementModel:
            available, detail = self._availability_for_model(model)
            entries.append(
                {
                    "id": model.value,
                    "label": MODEL_LABELS[model],
                    "description": MODEL_DESCRIPTIONS[model],
                    "available": available,
                    "detail": detail,
                    "experimental": model == EnhancementModel.STUDIO,
                    "default": model == self.default_model,
                }
            )
        return entries

    def is_model_available(self, model: EnhancementModel | str) -> bool:
        normalized = EnhancementModel(model)
        available, _detail = self._availability_for_model(normalized)
        return available

    def cancel(self, job_id: str) -> None:
        with self._lock:
            proc = self._processes.get(job_id)
        if proc and proc.poll() is None:
            proc.terminate()

    def enhance(
        self,
        *,
        job_id: str,
        enhancement_model: EnhancementModel,
        input_audio_path: Path,
        output_format: OutputFormat,
        output_base_path: Path,
        on_stage: Callable[[str, float, str, int | None], None],
        cancel_check: Callable[[], bool],
    ) -> Path:
        model = EnhancementModel(enhancement_model)
        available, detail = self._availability_for_model(model)
        if not available:
            raise EnhancementRuntimeError(f"{MODEL_LABELS[model]} is not available on this machine. {detail}".strip())

        if cancel_check():
            raise JobCancelledError("job cancelled")

        if model == EnhancementModel.NONE:
            on_stage("prepare", 0.12, "Preparing source audio without enhancement.", 4)
            on_stage("enhance", 0.82, "Skipping enhancement and keeping the original audio quality.", 2)
            final_path = self._write_passthrough_output(
                input_audio_path=input_audio_path,
                output_format=output_format,
                output_base_path=output_base_path,
            )
            on_stage("finalize", 0.96, "Saving audio without enhancement.", 2)
            return final_path

        with tempfile.TemporaryDirectory(prefix=f"radcast_{job_id}_") as tmp:
            tmp_path = Path(tmp)
            in_dir = tmp_path / "in"
            out_dir = tmp_path / "out"
            in_dir.mkdir(parents=True, exist_ok=True)
            out_dir.mkdir(parents=True, exist_ok=True)

            on_stage("prepare", 0.12, f"Preparing source audio for {MODEL_LABELS[model]}")
            in_wav = in_dir / "input.wav"
            input_filter = self._input_filter_for_model(model)
            if input_audio_path.suffix.lower() == ".wav" and not input_filter:
                in_wav.write_bytes(input_audio_path.read_bytes())
            else:
                run_ffmpeg_convert(input_audio_path, in_wav, audio_filters=input_filter)
            input_duration_seconds = probe_duration_seconds(in_wav)

            if cancel_check():
                raise JobCancelledError("job cancelled")

            command, use_shell, initial_detail = self._build_backend_command(model=model, in_dir=in_dir, in_wav=in_wav, out_dir=out_dir)
            expected_runtime_seconds = _estimate_runtime_seconds(
                input_duration_seconds,
                device=self.device,
                nfe=self.nfe,
                enhancement_model=model,
            )
            timeout_seconds = _estimate_timeout_seconds(expected_runtime_seconds, enhancement_model=model)
            on_stage("enhance", 0.2, initial_detail, None)
            backend_log_path = tmp_path / f"{model.value}.backend.log"
            with backend_log_path.open("w+", encoding="utf-8") as backend_log:
                try:
                    proc = subprocess.Popen(
                        ["/bin/bash", "-lc", command] if use_shell else command,
                        stdout=backend_log,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                except FileNotFoundError as exc:
                    raise EnhancementRuntimeError(self._missing_command_message(model)) from exc

                with self._lock:
                    self._processes[job_id] = proc

                started = time.monotonic()
                try:
                    while proc.poll() is None:
                        if cancel_check():
                            proc.terminate()
                            raise JobCancelledError("job cancelled")
                        elapsed = time.monotonic() - started
                        if elapsed >= timeout_seconds:
                            _terminate_process(proc)
                            log_tail = _tail_backend_log(backend_log_path)
                            message = f"{MODEL_LABELS[model]} timed out after {int(round(elapsed))}s on the helper device."
                            if log_tail:
                                message = f"{message}\n\nRecent backend output:\n{log_tail}"
                            raise EnhancementRuntimeError(message)
                        progress = _estimate_progress(elapsed, expected_runtime_seconds)
                        eta_seconds = _estimate_remaining_seconds(elapsed, expected_runtime_seconds)
                        detail_text = _progress_detail_for_model(model, elapsed, expected_runtime_seconds, eta_seconds)
                        on_stage("enhance", progress, detail_text, eta_seconds)
                        time.sleep(0.6)

                    proc.wait()
                    if proc.returncode != 0:
                        msg = _tail_backend_log(backend_log_path) or "Enhancement process failed"
                        raise EnhancementRuntimeError(msg[-2000:])
                finally:
                    with self._lock:
                        self._processes.pop(job_id, None)

            if cancel_check():
                raise JobCancelledError("job cancelled")

            enhanced_wav = self._collect_backend_output(model=model, out_dir=out_dir)

            on_stage("finalize", 0.96, "Saving the enhanced audio", 8)
            output_base_path.parent.mkdir(parents=True, exist_ok=True)
            output_filter = self._output_filter_for_model(model)

            if output_format == OutputFormat.WAV:
                final_path = output_base_path.with_suffix(".wav")
                if output_filter:
                    run_ffmpeg_convert(enhanced_wav, final_path, audio_filters=output_filter)
                else:
                    final_path.write_bytes(enhanced_wav.read_bytes())
                return final_path

            final_path = output_base_path.with_suffix(".mp3")
            run_ffmpeg_convert(enhanced_wav, final_path, audio_filters=output_filter)
            return final_path

    def _write_passthrough_output(
        self,
        *,
        input_audio_path: Path,
        output_format: OutputFormat,
        output_base_path: Path,
    ) -> Path:
        output_base_path.parent.mkdir(parents=True, exist_ok=True)
        input_suffix = input_audio_path.suffix.lower()
        if output_format == OutputFormat.WAV:
            final_path = output_base_path.with_suffix(".wav")
            if input_suffix == ".wav":
                shutil.copy2(input_audio_path, final_path)
            else:
                run_ffmpeg_convert(input_audio_path, final_path)
            return final_path

        final_path = output_base_path.with_suffix(".mp3")
        if input_suffix == ".mp3":
            shutil.copy2(input_audio_path, final_path)
        else:
            run_ffmpeg_convert(input_audio_path, final_path)
        return final_path

    def _availability_for_model(self, model: EnhancementModel) -> tuple[bool, str]:
        if model == EnhancementModel.NONE:
            return True, "Runs optional silence and filler cleanup without changing the enhancement model."
        if model == EnhancementModel.RESEMBLE:
            available = _command_available(self.resemble_command)
            return available, "Install resemble-enhance to enable it." if not available else "Installed."
        if model == EnhancementModel.STUDIO:
            available = _command_available(self.studio_command) and _python_modules_available(
                ["numpy", "scipy", "soundfile", "resemble_enhance", "torchaudio"]
            )
            detail = (
                "Custom dereverb plus Resemble Enhance is installed."
                if available
                else "Install the RADcast package with Studio dependencies to enable this backend."
            )
            return available, detail
        if model == EnhancementModel.STUDIO_V18:
            module_names = ["numpy", "scipy", "soundfile", "resemble_enhance", "torchaudio"]
            if self.studio_v18_dereverb_method == "nara":
                module_names.append("nara_wpe")
            available = _command_available(self.studio_command) and _python_modules_available(
                module_names
            )
            detail = (
                "RADcast Optimized path is installed."
                if available
                else "Install the RADcast package with Studio dependencies to enable this backend."
            )
            return available, detail
        if model == EnhancementModel.DEEPFILTERNET:
            available = _command_available(self.deepfilternet_command)
            detail = f"Uses official {self.deepfilternet_model} weights." if available else "Install deepfilternet to enable it."
            return available, detail
        return False, "This backend is not configured."

    def _build_backend_command(self, *, model: EnhancementModel, in_dir: Path, in_wav: Path, out_dir: Path) -> tuple[list[str] | str, bool, str]:
        if model == EnhancementModel.RESEMBLE:
            return (
                [
                    *self.resemble_command,
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
                ],
                False,
                "Loading Resemble Enhance. First run can take longer.",
            )
        if model == EnhancementModel.STUDIO:
            return (
                [
                    *self.studio_command,
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
                ],
                False,
                "Loading Studio Cleanup. First run can take longer.",
            )
        if model == EnhancementModel.STUDIO_V18:
            command = [
                *self.studio_command,
                str(in_dir),
                str(out_dir),
                "--suffix",
                ".wav",
                "--device",
                self.device,
                "--nfe",
                str(self.studio_v18_nfe),
                "--lambd",
                str(self.studio_v18_lambd),
                "--tau",
                str(self.studio_v18_tau),
                "--dereverb-method",
                self.studio_v18_dereverb_method,
            ]
            if self.studio_v18_dereverb_method == "nara":
                command.extend(
                    [
                        "--nara-chunk-seconds",
                        str(self.studio_v18_nara_chunk_seconds),
                        "--nara-overlap-seconds",
                        str(self.studio_v18_nara_overlap_seconds),
                        "--nara-taps",
                        str(self.studio_v18_nara_taps),
                        "--nara-delay",
                        str(self.studio_v18_nara_delay),
                        "--nara-iterations",
                        str(self.studio_v18_nara_iterations),
                        "--nara-psd-context",
                        str(self.studio_v18_nara_psd_context),
                    ]
                )
            else:
                command.extend(
                    [
                        "--wpe-taps",
                        str(self.studio_v18_wpe_taps),
                        "--wpe-delay",
                        str(self.studio_v18_wpe_delay),
                        "--wpe-iterations",
                        str(self.studio_v18_wpe_iterations),
                    ]
                )
            return (
                command,
                False,
                "Loading RADcast Optimized. First run can take longer.",
            )
        if model == EnhancementModel.DEEPFILTERNET:
            command = [
                *self.deepfilternet_command,
                "--output-dir",
                str(out_dir),
                "--model-base-dir",
                self.deepfilternet_model,
                "--log-level",
                "info",
                "--no-suffix",
            ]
            if self.deepfilternet_post_filter:
                command.append("--pf")
            command.append(str(in_wav))
            return command, False, f"Loading {MODEL_LABELS[model]}. First run can take longer while weights download."
        raise EnhancementRuntimeError(f"{MODEL_LABELS.get(model, str(model))} is not configured")

    def _collect_backend_output(self, *, model: EnhancementModel, out_dir: Path) -> Path:
        out_candidates = sorted(out_dir.glob("**/*.wav"))
        if not out_candidates:
            out_candidates = sorted(out_dir.glob("**/*"))
        if not out_candidates:
            raise EnhancementRuntimeError(f"{MODEL_LABELS[model]} did not produce output audio")
        for candidate in out_candidates:
            if candidate.is_file():
                return candidate
        raise EnhancementRuntimeError(f"{MODEL_LABELS[model]} did not produce a readable output file")

    @staticmethod
    def _missing_command_message(model: EnhancementModel) -> str:
        if model in {EnhancementModel.STUDIO, EnhancementModel.STUDIO_V18}:
            return "Studio Cleanup command not found. Reinstall RADcast or set RADCAST_STUDIO_COMMAND."
        if model == EnhancementModel.DEEPFILTERNET:
            return "DeepFilterNet command not found. Install deepfilternet or set RADCAST_DEEPFILTERNET_COMMAND."
        return "Enhancement command not found. Install resemble-enhance or set RADCAST_ENHANCE_COMMAND."

    def output_tuning_label_for_model(self, model: EnhancementModel) -> str | None:
        return current_audio_tuning_label(model)

    def _output_filter_for_model(self, model: EnhancementModel) -> str:
        if model == EnhancementModel.STUDIO:
            return self.studio_postfilter
        if model == EnhancementModel.STUDIO_V18:
            return self.studio_v18_postfilter
        return self.postfilter

    def _input_filter_for_model(self, model: EnhancementModel) -> str:
        if model == EnhancementModel.STUDIO_V18:
            return self.studio_v18_prefilter
        return self.prefilter


def _parse_model(raw: str | None, default: str) -> EnhancementModel:
    value = (raw or default or DEFAULT_ENHANCEMENT_MODEL).strip().lower()
    try:
        return EnhancementModel(value)
    except ValueError:
        return EnhancementModel(DEFAULT_ENHANCEMENT_MODEL)


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


def _safe_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_command(command_raw: str) -> list[str]:
    raw = command_raw or DEFAULT_ENHANCE_COMMAND
    parts = shlex.split(raw) if raw else [DEFAULT_ENHANCE_COMMAND]
    executable = parts[0]

    if "/" in executable:
        return parts

    venv_candidate = Path(sys.executable).with_name(executable)
    if venv_candidate.exists():
        parts[0] = str(venv_candidate)
        return parts

    system_candidate = shutil.which(executable)
    if system_candidate:
        parts[0] = system_candidate

    return parts


def _command_available(command: list[str]) -> bool:
    if not command:
        return False
    executable = command[0]
    if "/" in executable:
        return Path(executable).exists()
    return shutil.which(executable) is not None


def _python_modules_available(module_names: list[str]) -> bool:
    return all(find_spec(name) is not None for name in module_names)


def _estimate_runtime_seconds(duration_seconds: float, *, device: str, nfe: int, enhancement_model: EnhancementModel) -> int:
    safe_duration = max(1.0, float(duration_seconds))
    normalized_device = (device or DEFAULT_ENHANCE_DEVICE).strip().lower()
    accelerated = normalized_device.startswith("cuda") or normalized_device == "mps"

    if enhancement_model == EnhancementModel.NONE:
        estimate = 2.0 + (safe_duration * 0.12)
        return max(3, min(int(round(estimate)), 30))

    if enhancement_model == EnhancementModel.DEEPFILTERNET:
        if accelerated:
            base_seconds = 6.0
            per_second = 0.6
            minimum = 8
        else:
            base_seconds = 8.0
            per_second = 0.9
            minimum = 10
        estimate = base_seconds + (safe_duration * per_second)
        return max(minimum, min(int(round(estimate)), 20 * 60))

    if enhancement_model in {EnhancementModel.STUDIO, EnhancementModel.STUDIO_V18}:
        if accelerated:
            base_seconds = 24.0
            per_second = 2.8
            minimum = 32
        else:
            base_seconds = 58.0
            per_second = 5.8
            minimum = 72
        estimate = base_seconds + (safe_duration * per_second)
        return max(minimum, min(int(round(estimate)), 40 * 60))

    quality_factor = max(0.65, float(nfe) / float(DEFAULT_ENHANCE_NFE))
    if accelerated:
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
        eased = ratio ** 0.98
        return min(0.82, 0.18 + (0.60 * eased))

    overtime_ratio = min(1.0, (ratio - 1.0) / 1.4)
    return min(0.94, 0.82 + (0.12 * overtime_ratio))


def _estimate_remaining_seconds(elapsed_seconds: float, expected_runtime_seconds: int) -> int | None:
    if elapsed_seconds < 8.0:
        return None

    expected = max(1.0, float(expected_runtime_seconds))
    remaining = expected - elapsed_seconds
    if remaining > 0:
        return int(round(remaining))

    overtime = max(0.0, elapsed_seconds - expected)
    tail_seconds = max(expected * 0.14, 12.0)
    overtime_buffer = max(0.0, min(expected * 0.18, overtime * 0.3))
    return int(round(max(8.0, tail_seconds - overtime_buffer)))


def _estimate_timeout_seconds(expected_runtime_seconds: int, *, enhancement_model: EnhancementModel) -> int:
    expected = max(1, int(expected_runtime_seconds))
    if enhancement_model in {EnhancementModel.STUDIO, EnhancementModel.STUDIO_V18}:
        return max(12 * 60, int(round(expected * 2.75)), expected + (4 * 60))
    if enhancement_model == EnhancementModel.RESEMBLE:
        return max(8 * 60, int(round(expected * 2.4)), expected + (2 * 60))
    if enhancement_model == EnhancementModel.DEEPFILTERNET:
        return max(6 * 60, int(round(expected * 2.2)), expected + 90)
    return max(2 * 60, int(round(expected * 2.0)))


def _terminate_process(proc: subprocess.Popen[str]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _tail_backend_log(log_path: Path, *, max_chars: int = 2000) -> str:
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _progress_detail_for_model(
    model: EnhancementModel,
    elapsed_seconds: float,
    expected_runtime_seconds: int,
    eta_seconds: int | None,
) -> str:
    if model == EnhancementModel.NONE:
        if eta_seconds is None:
            return "Keeping the original audio quality. Finishing soon."
        return "Keeping the original audio quality."
    label = MODEL_LABELS[model]
    warmup_seconds = min(10.0, expected_runtime_seconds * 0.18)
    if elapsed_seconds < warmup_seconds:
        return f"Loading {label}. First run can take longer."
    if eta_seconds is None:
        return f"Improving audio with {label}. Finishing soon."
    if eta_seconds <= 12:
        return f"Improving audio with {label}. Final render can take a little longer."
    return f"Improving audio with {label}."


def _resolve_enhance_device(raw_device: str | None) -> str:
    configured = str(raw_device or "").strip().lower()
    if configured:
        return configured

    auto_detected = _detect_accelerated_device()
    if auto_detected:
        return auto_detected
    return DEFAULT_ENHANCE_DEVICE


def _detect_accelerated_device() -> str | None:
    try:
        import torch
    except Exception:
        return None

    try:
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass

    try:
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            if torch.backends.mps.is_built() and torch.backends.mps.is_available():
                return "mps"
    except Exception:
        pass

    return None
