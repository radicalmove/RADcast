"""Audio enhancement service with pluggable backend models."""

from __future__ import annotations

import os
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
    DEFAULT_STUDIO_V18_LAMBD,
    DEFAULT_STUDIO_V18_NFE,
    DEFAULT_STUDIO_V18_POSTFILTER,
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
    EnhancementModel.RESEMBLE: "Resemble Enhance",
    EnhancementModel.DEEPFILTERNET: "DeepFilterNet3",
    EnhancementModel.STUDIO: "Studio Cleanup",
    EnhancementModel.STUDIO_V18: "Studio v18",
}

MODEL_DESCRIPTIONS = {
    EnhancementModel.RESEMBLE: "Current RADcast backend. Strong cleanup, but can sound more processed.",
    EnhancementModel.DEEPFILTERNET: "Official DeepFilterNet3 speech enhancement. Usually more natural and less compressed.",
    EnhancementModel.STUDIO: "Custom late-reverb suppression plus Resemble Enhance. Built to chase a drier studio-mic sound.",
    EnhancementModel.STUDIO_V18: "Current best local Studio candidate. Stronger dereverb plus lighter restoration tuned toward a close-mic podcast sound.",
}


def current_audio_tuning_label(model: EnhancementModel | None = None) -> str:
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
        self.device = os.environ.get("RADCAST_ENHANCE_DEVICE", DEFAULT_ENHANCE_DEVICE).strip() or DEFAULT_ENHANCE_DEVICE
        self.nfe = _safe_int(os.environ.get("RADCAST_ENHANCE_NFE"), DEFAULT_ENHANCE_NFE)
        self.lambd = _safe_float(os.environ.get("RADCAST_ENHANCE_LAMBD"), DEFAULT_ENHANCE_LAMBD)
        self.tau = _safe_float(os.environ.get("RADCAST_ENHANCE_TAU"), DEFAULT_ENHANCE_TAU)
        self.prefilter = os.environ.get("RADCAST_ENHANCE_PREFILTER", DEFAULT_ENHANCE_PREFILTER).strip()
        self.postfilter = os.environ.get("RADCAST_ENHANCE_POSTFILTER", DEFAULT_ENHANCE_POSTFILTER).strip()
        self.studio_postfilter = os.environ.get("RADCAST_STUDIO_POSTFILTER", DEFAULT_STUDIO_POSTFILTER).strip()
        self.studio_v18_postfilter = os.environ.get("RADCAST_STUDIO_V18_POSTFILTER", DEFAULT_STUDIO_V18_POSTFILTER).strip()
        self.studio_v18_nfe = _safe_int(os.environ.get("RADCAST_STUDIO_V18_NFE"), DEFAULT_STUDIO_V18_NFE)
        self.studio_v18_lambd = _safe_float(os.environ.get("RADCAST_STUDIO_V18_LAMBD"), DEFAULT_STUDIO_V18_LAMBD)
        self.studio_v18_tau = _safe_float(os.environ.get("RADCAST_STUDIO_V18_TAU"), DEFAULT_STUDIO_V18_TAU)
        self.studio_v18_wpe_taps = _safe_int(os.environ.get("RADCAST_STUDIO_V18_WPE_TAPS"), DEFAULT_STUDIO_V18_WPE_TAPS)
        self.studio_v18_wpe_delay = _safe_int(os.environ.get("RADCAST_STUDIO_V18_WPE_DELAY"), DEFAULT_STUDIO_V18_WPE_DELAY)
        self.studio_v18_wpe_iterations = _safe_int(
            os.environ.get("RADCAST_STUDIO_V18_WPE_ITERATIONS"),
            DEFAULT_STUDIO_V18_WPE_ITERATIONS,
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
                    "experimental": model in {EnhancementModel.STUDIO, EnhancementModel.STUDIO_V18},
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

        with tempfile.TemporaryDirectory(prefix=f"radcast_{job_id}_") as tmp:
            tmp_path = Path(tmp)
            in_dir = tmp_path / "in"
            out_dir = tmp_path / "out"
            in_dir.mkdir(parents=True, exist_ok=True)
            out_dir.mkdir(parents=True, exist_ok=True)

            on_stage("prepare", 0.12, f"Preparing source audio for {MODEL_LABELS[model]}")
            in_wav = in_dir / "input.wav"
            if input_audio_path.suffix.lower() == ".wav" and not self.prefilter:
                in_wav.write_bytes(input_audio_path.read_bytes())
            else:
                run_ffmpeg_convert(input_audio_path, in_wav, audio_filters=self.prefilter)
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
            on_stage("enhance", 0.2, initial_detail, None)
            try:
                proc = subprocess.Popen(
                    ["/bin/bash", "-lc", command] if use_shell else command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
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
                    progress = _estimate_progress(elapsed, expected_runtime_seconds)
                    eta_seconds = _estimate_remaining_seconds(elapsed, expected_runtime_seconds)
                    detail_text = _progress_detail_for_model(model, elapsed, expected_runtime_seconds, eta_seconds)
                    on_stage("enhance", progress, detail_text, eta_seconds)
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

    def _availability_for_model(self, model: EnhancementModel) -> tuple[bool, str]:
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
            available = _command_available(self.studio_command) and _python_modules_available(
                ["numpy", "scipy", "soundfile", "resemble_enhance", "torchaudio"]
            )
            detail = (
                "Version 18 Studio path is installed."
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
                    str(self.studio_v18_nfe),
                    "--lambd",
                    str(self.studio_v18_lambd),
                    "--tau",
                    str(self.studio_v18_tau),
                    "--wpe-taps",
                    str(self.studio_v18_wpe_taps),
                    "--wpe-delay",
                    str(self.studio_v18_wpe_delay),
                    "--wpe-iterations",
                    str(self.studio_v18_wpe_iterations),
                ],
                False,
                "Loading Studio v18. First run can take longer.",
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

    def output_tuning_label_for_model(self, model: EnhancementModel) -> str:
        return current_audio_tuning_label(model)

    def _output_filter_for_model(self, model: EnhancementModel) -> str:
        if model == EnhancementModel.STUDIO:
            return self.studio_postfilter
        if model == EnhancementModel.STUDIO_V18:
            return self.studio_v18_postfilter
        return self.postfilter


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
            base_seconds = 18.0
            per_second = 2.4
            minimum = 24
        else:
            base_seconds = 42.0
            per_second = 5.0
            minimum = 55
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


def _progress_detail_for_model(
    model: EnhancementModel,
    elapsed_seconds: float,
    expected_runtime_seconds: int,
    eta_seconds: int | None,
) -> str:
    label = MODEL_LABELS[model]
    warmup_seconds = min(10.0, expected_runtime_seconds * 0.18)
    if elapsed_seconds < warmup_seconds:
        return f"Loading {label}. First run can take longer."
    if eta_seconds is None:
        return f"Improving audio with {label}. Finishing soon."
    return f"Improving audio with {label}."
