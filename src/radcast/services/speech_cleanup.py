"""Speech-aware post-processing for long silences, filler words, and captions."""

from __future__ import annotations

import gc
import os
import re
import shutil
import tempfile
import time
import wave
import math
import platform
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Callable

import numpy as np

from radcast.exceptions import EnhancementRuntimeError, JobCancelledError
from radcast.models import CaptionFormat, CaptionQualityMode, FillerRemovalMode, OutputFormat
from radcast.progress import estimate_caption_seconds, estimate_speech_cleanup_seconds
from radcast.services.caption_backend_selection import (
    CaptionBackendSelectionError,
    resolve_caption_backend_id,
)
from radcast.services.caption_cue_shaping import shape_lecture_caption_cues
from radcast.services.caption_quality_policy import (
    CaptionQualityPolicy,
    resolve_caption_quality_policy,
)
from radcast.services.caption_review import (
    CaptionAccessibilityAssessment,
    CaptionQualityReport,
    CaptionReviewFlag,
    assess_caption_accessibility,
    build_caption_export_quality_report,
    build_caption_quality_report,
    format_caption_review_document,
    sanitize_review_candidate_text,
    is_review_system_text,
)
from radcast.services.caption_backends import (
    CaptionBackend,
    CaptionTranscriptionResult,
    FasterWhisperCaptionBackend,
    MlxWhisperCaptionBackend,
    WhisperCppCaptionBackend,
)
from radcast.utils.audio import probe_duration_seconds, run_ffmpeg_convert

CleanupStageCallback = Callable[[float, str, int | None], None]

_FILLER_WORDS = {
    "ah",
    "ahh",
    "erm",
    "er",
    "uh",
    "uhh",
    "uhm",
    "um",
    "umm",
}
_MIN_COMPACTABLE_GAP_SECONDS = 0.35
_FILLER_MIN_DURATION_SECONDS = 0.08
_FILLER_MAX_DURATION_SECONDS = 1.35
_CUT_CROSSFADE_SECONDS = 0.012
_TRANSCRIBE_PROGRESS_MIN_INTERVAL_SECONDS = 0.8
_TOKEN_RE = re.compile(r"[^a-z']+")
_AGGRESSIVE_TRANSCRIBE_WINDOW_SECONDS = 8.0
_AGGRESSIVE_TRANSCRIBE_OVERLAP_SECONDS = 2.0
_CAPTION_FAST_WINDOW_SECONDS = 8.0
_CAPTION_FAST_OVERLAP_SECONDS = 1.5
_CAPTION_ACCURATE_WINDOW_SECONDS = 12.0
_CAPTION_ACCURATE_OVERLAP_SECONDS = 2.5
_CAPTION_REVIEWED_WINDOW_SECONDS = 16.0
_CAPTION_REVIEWED_OVERLAP_SECONDS = 3.0
_CAPTION_REVIEW_SWEEP_CONTEXT_SECONDS = 1.8
_CAPTION_MAX_CUE_DURATION_SECONDS = 6.0
_CAPTION_MAX_CUE_CHARACTERS = 84
_CAPTION_MAX_CUE_WORDS = 14
_CAPTION_MAX_LINE_CHARACTERS = 42
_AGGRESSIVE_FILLER_PROMPT = (
    "Transcribe all spoken disfluencies exactly, including um, ums, uh, uhh, ah, ahh, erm, mm, and hesitation sounds."
)
_COMMON_MAORI_TERMS = (
    "Aotearoa",
    "aroha",
    "haka",
    "hāngī",
    "hui",
    "iwi",
    "kai",
    "kaiako",
    "kaitiaki",
    "kaitiakitanga",
    "kaumātua",
    "kaupapa",
    "kaupapa Māori",
    "karakia",
    "kia ora",
    "kōrero",
    "kotahitanga",
    "kuia",
    "mana",
    "mana whenua",
    "manaakitanga",
    "mātauranga",
    "mātauranga Māori",
    "Māori",
    "marae",
    "mokopuna",
    "muru",
    "noa",
    "Pākehā",
    "pōwhiri",
    "pūrākau",
    "rangatahi",
    "rangatiratanga",
    "taonga",
    "taonga tuku iho",
    "tamariki",
    "tangata whenua",
    "tapu",
    "te ao Māori",
    "te reo Māori",
    "Te Tiriti o Waitangi",
    "tikanga",
    "tikanga Māori",
    "utu",
    "waka",
    "wānanga",
    "whakapapa",
    "whakataukī",
    "whānau",
    "whanaungatanga",
)
_NZ_ENGLISH_VARIANTS = (
    "organisation",
    "organise",
    "recognise",
    "behaviour",
    "colour",
    "favour",
    "honour",
    "labour",
    "neighbour",
    "centre",
    "centred",
    "metre",
    "litre",
    "theatre",
    "fibre",
    "defence",
    "pretence",
    "travelling",
    "traveller",
    "labelled",
    "modelling",
    "cancelled",
    "analysing",
    "analysed",
    "practise",
    "licence",
    "enrolment",
    "jewellery",
    "counselling",
    "authorised",
    "emphasise",
    "programme",
    "cheque",
)
_MAORI_GLOSSARY_PROMPT = (
    "This audio may include te reo Māori words. Prefer correct spellings and macrons when spoken clearly, such as "
    + ", ".join(_COMMON_MAORI_TERMS)
    + "."
)
_NZ_ENGLISH_STYLE_PROMPT = (
    "Prefer New Zealand English spelling rather than US spelling when there is no strong contrary signal, for example "
    + ", ".join(_NZ_ENGLISH_VARIANTS)
    + "."
)
_CAPTION_REVIEW_PROMPT = (
    "Review low-confidence transcript lines carefully. Prefer the spoken wording, preserve names and te reo Māori, "
    "and correct likely misheard words rather than paraphrasing."
)


@dataclass(frozen=True)
class TranscriptWordTiming:
    text: str
    start: float
    end: float
    probability: float | None = None


@dataclass(frozen=True)
class TranscriptSegmentTiming:
    text: str
    start: float
    end: float
    average_probability: float | None = None


@dataclass(frozen=True)
class SpeechCleanupResult:
    applied: bool
    removed_pause_count: int
    removed_filler_count: int
    duration_seconds: float

    def summary_text(self) -> str:
        parts: list[str] = []
        if self.removed_pause_count > 0:
            parts.append(f"shortened {self.removed_pause_count} long pause{'s' if self.removed_pause_count != 1 else ''}")
        if self.removed_filler_count > 0:
            parts.append(f"removed {self.removed_filler_count} filler word{'s' if self.removed_filler_count != 1 else ''}")
        if not parts:
            return "No long silences or filler words needed trimming."
        return ", ".join(parts).capitalize() + "."


def _estimate_window_count(
    *,
    total_duration: float,
    window_seconds: float,
    overlap_seconds: float,
) -> int:
    safe_duration = max(0.0, float(total_duration))
    if safe_duration <= 0.0:
        return 1
    resolved_window_seconds = min(max(float(window_seconds), 1.0), safe_duration)
    resolved_overlap_seconds = min(float(overlap_seconds), max(0.0, resolved_window_seconds / 2.0))
    step_seconds = max(0.5, resolved_window_seconds - resolved_overlap_seconds)
    return max(1, int(math.ceil(max(safe_duration - resolved_window_seconds, 0.0) / step_seconds)) + 1)


def _windowed_stage_detail(detail: str, *, current_window: int, total_windows: int) -> str:
    base = str(detail or "").strip().rstrip(".")
    return f"{base}. Window {max(1, int(current_window))} of {max(1, int(total_windows))}."


def _caption_backend_display_name(backend: CaptionBackend) -> str:
    if backend.id == "whispercpp":
        return "whisper.cpp"
    if backend.id == "faster_whisper":
        return "faster-whisper"
    if backend.id == "mlx_whisper":
        return "mlx-whisper"
    return backend.id


def _caption_stage_detail(*, action: str, backend: CaptionBackend, model_size: str) -> str:
    backend_label = _caption_backend_display_name(backend)
    model_label = str(model_size or "").strip() or backend.default_model_size
    return f"{action} with {backend_label} ({model_label})"


def _indexed_stage_detail(detail: str, *, current_item: int, total_items: int) -> str:
    base = str(detail or "").strip().rstrip(".")
    return f"{base}. {max(1, int(current_item))} of {max(1, int(total_items))}."


@dataclass(frozen=True)
class CaptionExportResult:
    caption_path: Path
    caption_format: CaptionFormat
    segment_count: int
    review_path: Path | None = None
    quality_report: CaptionQualityReport | None = None
    accessibility_assessment: CaptionAccessibilityAssessment | None = None


@dataclass(frozen=True)
class CaptionTranscriptionProfile:
    model_size: str
    beam_size: int
    window_seconds: float
    overlap_seconds: float
    condition_on_previous_text: bool
    initial_prompt: str | None
    review_sweep: bool = False


@dataclass(frozen=True)
class FillerRemovalHeuristics:
    min_probability: float
    min_context_gap_seconds: float
    min_strong_side_gap_seconds: float
    single_side_gap_seconds: float
    two_sided_context_gap_seconds: float
    two_sided_min_gap_seconds: float
    run_max_internal_gap_seconds: float
    strong_probability: float
    lead_pad_cap_seconds: float
    tail_pad_cap_seconds: float
    lead_pad_ratio: float = 0.5
    tail_pad_ratio: float = 0.5
    always_accept_explicit_fillers: bool = False


_NORMAL_FILLER_HEURISTICS = FillerRemovalHeuristics(
    min_probability=0.28,
    min_context_gap_seconds=0.14,
    min_strong_side_gap_seconds=0.06,
    single_side_gap_seconds=0.15,
    two_sided_context_gap_seconds=0.1,
    two_sided_min_gap_seconds=0.04,
    run_max_internal_gap_seconds=0.18,
    strong_probability=0.34,
    lead_pad_cap_seconds=0.025,
    tail_pad_cap_seconds=0.05,
)

_AGGRESSIVE_FILLER_HEURISTICS = FillerRemovalHeuristics(
    min_probability=0.08,
    min_context_gap_seconds=0.11,
    min_strong_side_gap_seconds=0.04,
    single_side_gap_seconds=0.1,
    two_sided_context_gap_seconds=0.06,
    two_sided_min_gap_seconds=0.018,
    run_max_internal_gap_seconds=0.32,
    strong_probability=0.22,
    lead_pad_cap_seconds=0.035,
    tail_pad_cap_seconds=0.07,
    lead_pad_ratio=0.55,
    tail_pad_ratio=0.55,
    always_accept_explicit_fillers=True,
)


class SpeechCleanupService:
    def __init__(self) -> None:
        self.runtime_context = os.environ.get("RADCAST_RUNTIME_CONTEXT", "server").strip().lower() or "server"
        self.platform_name = platform.system()
        self.cleanup_model_size = os.environ.get("RADCAST_SPEECH_CLEANUP_MODEL", "small").strip() or "small"
        self.caption_fast_model_size = os.environ.get("RADCAST_CAPTION_FAST_MODEL", self.cleanup_model_size).strip() or self.cleanup_model_size
        self.caption_accurate_model_size = os.environ.get("RADCAST_CAPTION_ACCURATE_MODEL", "medium").strip() or "medium"
        self.caption_reviewed_model_size = os.environ.get("RADCAST_CAPTION_REVIEWED_MODEL", "large-v3").strip() or "large-v3"
        self.device = os.environ.get("RADCAST_SPEECH_CLEANUP_DEVICE", "auto").strip() or "auto"
        self.compute_type = os.environ.get("RADCAST_SPEECH_CLEANUP_COMPUTE_TYPE", "int8").strip() or "int8"
        self.transcribe_language = os.environ.get("RADCAST_SPEECH_CLEANUP_LANGUAGE", "en").strip().lower() or "en"
        self.beam_size = max(1, int(os.environ.get("RADCAST_SPEECH_CLEANUP_BEAM_SIZE", "3")))
        self.caption_fast_beam_size = max(1, int(os.environ.get("RADCAST_CAPTION_FAST_BEAM_SIZE", str(self.beam_size))))
        self.caption_accurate_beam_size = max(1, int(os.environ.get("RADCAST_CAPTION_ACCURATE_BEAM_SIZE", "3")))
        self.caption_reviewed_beam_size = max(1, int(os.environ.get("RADCAST_CAPTION_REVIEWED_BEAM_SIZE", "5")))
        faster_backend = FasterWhisperCaptionBackend(
            default_model_size=self.cleanup_model_size,
            device=self.device,
            compute_type=self.compute_type,
            transcribe_language=self.transcribe_language,
            default_beam_size=self.beam_size,
        )
        whispercpp_backend = WhisperCppCaptionBackend(
            default_model_size=self.cleanup_model_size,
            transcribe_language=self.transcribe_language,
            default_beam_size=self.beam_size,
        )
        mlx_backend = MlxWhisperCaptionBackend(
            default_model_size=self.caption_reviewed_model_size,
            transcribe_language=self.transcribe_language,
        )
        self._caption_backends: dict[str, CaptionBackend] = {
            faster_backend.id: faster_backend,
            whispercpp_backend.id: whispercpp_backend,
            mlx_backend.id: mlx_backend,
        }
        available_backends = {
            backend_id
            for backend_id, backend in self._caption_backends.items()
            if backend.capability_status()[0]
        }
        try:
            self.caption_backend_id = resolve_caption_backend_id(
                os.environ.get("RADCAST_CAPTION_BACKEND", "auto"),
                platform_name=self.platform_name,
                runtime_context=self.runtime_context,
                available_backends=available_backends,
            )
        except CaptionBackendSelectionError as exc:
            raise EnhancementRuntimeError(str(exc)) from exc
        self._caption_backend = self._caption_backends[self.caption_backend_id]
        self._faster_whisper_backend = faster_backend
        self._mlx_whisper_backend = mlx_backend
        # Preserve the existing cache inspection surface while the orchestration layer
        # is being migrated to backend-owned transcription.
        self._models = getattr(self._caption_backend, "_models", {})

    def estimate_caption_runtime_seconds(
        self,
        duration_seconds: float,
        *,
        quality_mode: CaptionQualityMode = CaptionQualityMode.REVIEWED,
    ) -> int:
        normalized_quality = _normalize_caption_quality_mode(quality_mode)
        base_seconds = estimate_caption_seconds(duration_seconds, quality_mode=normalized_quality)
        profile = self._caption_profile_for_mode(normalized_quality, caption_prompt=None)
        policy = self.caption_quality_policy_for_mode(normalized_quality)
        first_pass_backend = self._caption_backend_for_id(policy.first_pass_backend_id)
        first_pass_model_size = policy.first_pass_model_size
        if normalized_quality == CaptionQualityMode.REVIEWED:
            review_backend = self._caption_backend_for_id(policy.review_backend_id)
            first_pass_ready = self._model_cache_ready(first_pass_model_size, backend=first_pass_backend)
            review_ready = self._model_cache_ready(policy.review_model_size, backend=review_backend)
            if first_pass_ready and review_ready:
                return base_seconds
            cold_start_seconds = 0
            if not first_pass_ready:
                cold_start_seconds += 95
            if not review_ready:
                cold_start_seconds += 80
            return min(base_seconds + cold_start_seconds, 24 * 60)
        if self._model_cache_ready(profile.model_size):
            return base_seconds
        if normalized_quality == CaptionQualityMode.FAST:
            cold_start_seconds = 18
        elif normalized_quality == CaptionQualityMode.ACCURATE:
            cold_start_seconds = 95
        else:
            cold_start_seconds = 145
        if self._model_cache_ready(first_pass_model_size, backend=first_pass_backend):
            return base_seconds
        return min(base_seconds + cold_start_seconds, 22 * 60)

    @staticmethod
    def cleanup_requested(max_silence_seconds: float | None, remove_filler_words: bool) -> bool:
        return max_silence_seconds is not None or bool(remove_filler_words)

    def capability_status(self) -> tuple[bool, str]:
        if find_spec("faster_whisper") is None:
            return False, "Install faster-whisper to enable long-silence trimming, filler-word cleanup, and caption export."
        reviewed_policy = self.caption_quality_policy_for_mode(CaptionQualityMode.REVIEWED)
        return True, (
            "Speech cleanup and caption export are available with faster-whisper "
            f"(cleanup: {self.cleanup_model_size}, captions: {self.caption_accurate_model_size}, review: {reviewed_policy.review_model_size})."
        )

    def caption_quality_policy_for_mode(self, caption_quality_mode: CaptionQualityMode) -> CaptionQualityPolicy:
        normalized_quality = _normalize_caption_quality_mode(caption_quality_mode)
        if normalized_quality == CaptionQualityMode.FAST:
            first_pass_model_size = self.caption_fast_model_size
            first_pass_beam_size = self.caption_fast_beam_size
            review_model_size = self.caption_fast_model_size
            review_beam_size = self.caption_fast_beam_size
        elif normalized_quality == CaptionQualityMode.ACCURATE:
            first_pass_model_size = self.caption_accurate_model_size
            first_pass_beam_size = self.caption_accurate_beam_size
            review_model_size = self.caption_reviewed_model_size
            review_beam_size = self.caption_reviewed_beam_size
        else:
            first_pass_model_size = self.caption_accurate_model_size
            first_pass_beam_size = self.caption_accurate_beam_size
            review_model_size = self.caption_reviewed_model_size
            review_beam_size = self.caption_reviewed_beam_size
        policy_backend_id = self.caption_backend_id
        if (
            normalized_quality == CaptionQualityMode.REVIEWED
            and self.runtime_context == "local_helper"
            and self.platform_name.lower() == "darwin"
            and self._mlx_whisper_backend.capability_status()[0]
        ):
            policy_backend_id = self._mlx_whisper_backend.id
        return resolve_caption_quality_policy(
            quality_mode=normalized_quality,
            runtime_context=self.runtime_context,
            platform_name=self.platform_name,
            backend_id=policy_backend_id,
            first_pass_model_size=first_pass_model_size,
            first_pass_beam_size=first_pass_beam_size,
            review_model_size=review_model_size,
            review_beam_size=review_beam_size,
        )

    def _caption_review_backend_config(self, caption_quality_mode: CaptionQualityMode) -> tuple[CaptionBackend, str]:
        policy = self.caption_quality_policy_for_mode(caption_quality_mode)
        review_backend = self._caption_backend_for_id(policy.review_backend_id)
        return review_backend, policy.review_model_size

    def estimate_runtime_seconds(
        self,
        duration_seconds: float,
        *,
        remove_filler_words: bool,
        filler_removal_mode: FillerRemovalMode = FillerRemovalMode.AGGRESSIVE,
    ) -> int:
        return estimate_speech_cleanup_seconds(
            duration_seconds,
            remove_filler_words=remove_filler_words,
            filler_removal_mode=_normalize_filler_mode(filler_removal_mode),
        )

    def _caption_backend_for_id(self, backend_id: str) -> CaptionBackend:
        normalized_backend_id = str(backend_id or "").strip().lower()
        if normalized_backend_id == self._caption_backend.id:
            return self._caption_backend
        if normalized_backend_id == self._faster_whisper_backend.id:
            return self._faster_whisper_backend
        if normalized_backend_id == self._mlx_whisper_backend.id:
            return self._mlx_whisper_backend
        raise EnhancementRuntimeError(f"Unsupported caption review backend '{backend_id}'")

    def _model_cache_ready(self, model_size: str | None, *, backend: CaptionBackend | None = None) -> bool:
        selected_backend = backend or self._caption_backend
        resolved_model_size = str(model_size or "").strip()
        if not resolved_model_size:
            return False
        if resolved_model_size in selected_backend._models:
            return True
        if "/" in resolved_model_size:
            owner, repo = resolved_model_size.split("/", 1)
        else:
            owner, repo = "Systran", f"faster-whisper-{resolved_model_size}"
        repo_cache_name = f"models--{owner.replace('/', '--')}--{repo.replace('/', '--')}"
        cache_roots: list[Path] = []
        hf_home = os.environ.get("HF_HOME", "").strip()
        if hf_home:
            cache_roots.append(Path(hf_home) / "hub")
        hub_cache = os.environ.get("HUGGINGFACE_HUB_CACHE", "").strip()
        if hub_cache:
            cache_roots.append(Path(hub_cache))
        cache_roots.append(Path.home() / ".cache" / "huggingface" / "hub")
        return any((root / repo_cache_name).exists() for root in cache_roots)

    def cleanup_audio_file(
        self,
        *,
        audio_path: Path,
        output_format: OutputFormat,
        max_silence_seconds: float | None,
        remove_filler_words: bool,
        filler_removal_mode: FillerRemovalMode = FillerRemovalMode.AGGRESSIVE,
        on_stage: CleanupStageCallback | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> SpeechCleanupResult:
        if not self.cleanup_requested(max_silence_seconds, remove_filler_words):
            return SpeechCleanupResult(
                applied=False,
                removed_pause_count=0,
                removed_filler_count=0,
                duration_seconds=probe_duration_seconds(audio_path),
            )

        available, detail = self.capability_status()
        if not available:
            raise EnhancementRuntimeError(detail)

        if cancel_check and cancel_check():
            raise JobCancelledError("job cancelled")

        input_duration = probe_duration_seconds(audio_path)
        cleanup_started_at = time.monotonic()
        cleanup_eta_seconds = self.estimate_runtime_seconds(
            input_duration,
            remove_filler_words=remove_filler_words,
            filler_removal_mode=filler_removal_mode,
        )
        if on_stage:
            on_stage(
                0.02,
                "Transcribing speech timing for cleanup.",
                cleanup_eta_seconds,
            )

        with tempfile.TemporaryDirectory(prefix="radcast_cleanup_") as tmp:
            tmp_path = Path(tmp)
            analysis_wav = tmp_path / "analysis.wav"
            run_ffmpeg_convert(audio_path, analysis_wav)

            words, segments = self._transcribe_timeline(
                analysis_wav,
                total_duration=input_duration,
                started_at=cleanup_started_at,
                cleanup_eta_seconds=cleanup_eta_seconds,
                on_stage=on_stage,
                remove_filler_words=remove_filler_words,
                filler_removal_mode=filler_removal_mode,
                cancel_check=cancel_check,
            )

            if cancel_check and cancel_check():
                raise JobCancelledError("job cancelled")

            waveform, sample_rate = _read_pcm16_wav(analysis_wav)
            total_duration = waveform.shape[0] / float(sample_rate) if sample_rate else 0.0
            if on_stage:
                on_stage(
                    0.74,
                    "Reviewing speech gaps and filler words.",
                    _remaining_cleanup_eta(cleanup_started_at, cleanup_eta_seconds, floor_seconds=4),
                )
            filler_intervals, filler_count = self._filler_intervals(
                words=words,
                remove_filler_words=remove_filler_words,
                filler_removal_mode=filler_removal_mode,
            )
            silence_intervals, silence_count = self._silence_intervals(
                words=words,
                segments=segments,
                total_duration=total_duration,
                max_silence_seconds=max_silence_seconds,
                treat_fillers_as_removed=remove_filler_words,
            )
            removal_intervals = _merge_intervals([*filler_intervals, *silence_intervals])

            if not removal_intervals:
                duration_seconds = probe_duration_seconds(audio_path)
                return SpeechCleanupResult(
                    applied=False,
                    removed_pause_count=silence_count,
                    removed_filler_count=filler_count,
                    duration_seconds=duration_seconds,
                )

            if on_stage:
                on_stage(
                    0.9,
                    self._rewrite_detail(silence_count=silence_count, filler_count=filler_count),
                    _remaining_cleanup_eta(cleanup_started_at, cleanup_eta_seconds, floor_seconds=3),
                )

            edited = _splice_waveform(waveform, sample_rate=sample_rate, removal_intervals=removal_intervals)
            cleaned_wav = tmp_path / "cleaned.wav"
            _write_pcm16_wav(cleaned_wav, edited, sample_rate=sample_rate)

            final_tmp = tmp_path / f"final-output{audio_path.suffix.lower() or '.wav'}"
            if on_stage:
                on_stage(
                    0.97,
                    "Saving cleaned audio.",
                    _remaining_cleanup_eta(cleanup_started_at, cleanup_eta_seconds, floor_seconds=2),
                )
            if output_format == OutputFormat.WAV:
                shutil.copy2(cleaned_wav, final_tmp)
            else:
                run_ffmpeg_convert(cleaned_wav, final_tmp)
            final_tmp.replace(audio_path)

        return SpeechCleanupResult(
            applied=True,
            removed_pause_count=silence_count,
            removed_filler_count=filler_count,
            duration_seconds=probe_duration_seconds(audio_path),
        )

    def generate_caption_file(
        self,
        *,
        audio_path: Path,
        caption_format: CaptionFormat,
        caption_quality_mode: CaptionQualityMode = CaptionQualityMode.REVIEWED,
        caption_glossary: str | None = None,
        on_stage: CleanupStageCallback | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> CaptionExportResult:
        available, detail = self.capability_status()
        if not available:
            raise EnhancementRuntimeError(detail)

        if cancel_check and cancel_check():
            raise JobCancelledError("job cancelled")

        input_duration = probe_duration_seconds(audio_path)
        quality_mode = _normalize_caption_quality_mode(caption_quality_mode)
        policy = self.caption_quality_policy_for_mode(quality_mode)
        caption_prompt = _build_caption_prompt(caption_glossary)
        profile = self._caption_profile_for_mode(quality_mode, caption_prompt=caption_prompt)
        review_backend, review_model_size = self._caption_review_backend_config(quality_mode)
        caption_eta_seconds = self.estimate_caption_runtime_seconds(input_duration, quality_mode=quality_mode)
        total_windows = _estimate_window_count(
            total_duration=input_duration,
            window_seconds=profile.window_seconds,
            overlap_seconds=profile.overlap_seconds,
        )
        first_pass_backend = self._caption_backend_for_id(policy.first_pass_backend_id)
        first_pass_model_size = policy.first_pass_model_size
        stage_label = f"{policy.progress_label}: " if policy.policy_id == "quality_local_lecture" else ""
        started_at = time.monotonic()
        if on_stage:
            backend_detail = _caption_stage_detail(
                action="Transcribing speech for captions",
                backend=first_pass_backend,
                model_size=first_pass_model_size,
            )
            detail = f"{stage_label}{backend_detail}" if stage_label else backend_detail
            if not self._model_cache_ready(first_pass_model_size, backend=first_pass_backend):
                detail = f"Loading {first_pass_model_size} caption model and {detail.lower()}."
            on_stage(
                0.02,
                _windowed_stage_detail(detail, current_window=1, total_windows=total_windows),
                caption_eta_seconds if total_windows <= 1 else None,
            )

        with tempfile.TemporaryDirectory(prefix="radcast_captions_") as tmp:
            tmp_path = Path(tmp)
            analysis_wav = tmp_path / "analysis.wav"
            run_ffmpeg_convert(audio_path, analysis_wav)
            _words, segments = self._transcribe_timeline(
                analysis_wav,
                total_duration=input_duration,
                started_at=started_at,
                cleanup_eta_seconds=caption_eta_seconds,
                on_stage=on_stage,
                remove_filler_words=False,
                filler_removal_mode=FillerRemovalMode.AGGRESSIVE,
                transcribe_detail=f"{stage_label}{_caption_stage_detail(action='Transcribing speech for captions', backend=first_pass_backend, model_size=first_pass_model_size)}".strip(),
                cancel_check=cancel_check,
                force_windowed=True,
                preserve_fillers=False,
                backend=first_pass_backend,
                model_size=first_pass_model_size,
                beam_size=profile.beam_size,
                condition_on_previous_text=profile.condition_on_previous_text,
                initial_prompt=profile.initial_prompt,
                window_seconds=profile.window_seconds,
                overlap_seconds=profile.overlap_seconds,
            )
            segments = _dedupe_caption_segments(segments)

            if cancel_check and cancel_check():
                raise JobCancelledError("job cancelled")

            review_report = build_caption_quality_report(
                segments,
                strategy_id=policy.review_strategy_id,
            )
            if profile.review_sweep and review_report.flagged_segments:
                if on_stage:
                    review_detail = _caption_stage_detail(
                        action="Reviewing low-confidence caption lines",
                        backend=review_backend,
                        model_size=review_model_size,
                    )
                    if stage_label:
                        review_detail = f"{stage_label}{review_detail}"
                    on_stage(
                        0.82,
                        review_detail,
                        None,
                    )
                segments = self._review_and_correct_caption_segments(
                    analysis_wav=analysis_wav,
                    base_segments=segments,
                    quality_report=review_report,
                    prompt_text=caption_prompt,
                    on_stage=on_stage,
                    started_at=started_at,
                    caption_eta_seconds=caption_eta_seconds,
                    review_backend=review_backend,
                    review_model_size=review_model_size,
                    progress_label=policy.progress_label if policy.policy_id == "quality_local_lecture" else None,
                    cancel_check=cancel_check,
                )
                segments = _dedupe_caption_segments(segments)

            try:
                export_segments = shape_lecture_caption_cues(segments)
            except Exception:
                export_segments = segments
            export_segments = _dedupe_caption_segments(export_segments)
            critical_terms = _critical_caption_terms(caption_glossary)
            export_report = build_caption_quality_report(export_segments, critical_terms=critical_terms)
            outward_quality_report = build_caption_export_quality_report(
                review_report=review_report,
                export_report=export_report,
            )
            accessibility_assessment = assess_caption_accessibility(export_report)

            output_path = audio_path.with_suffix(f".{caption_format.value}")
            review_path = None
            if on_stage:
                on_stage(
                    0.92,
                    f"Writing {caption_format.value.upper()} captions.",
                    _remaining_cleanup_eta(started_at, caption_eta_seconds, floor_seconds=2),
                )
            output_path.write_text(
                _format_caption_document(export_segments, caption_format=caption_format),
                encoding="utf-8",
            )
            if review_report.review_recommended:
                review_path = output_path.parent / f"{output_path.name}.review.txt"
                review_path.write_text(
                    format_caption_review_document(
                        export_report,
                        displayed_total_segment_count=outward_quality_report.total_segment_count,
                    ),
                    encoding="utf-8",
                )
        return CaptionExportResult(
            caption_path=output_path,
            caption_format=caption_format,
            segment_count=len([segment for segment in export_segments if _clean_caption_text(segment.text)]),
            review_path=review_path,
            quality_report=outward_quality_report,
            accessibility_assessment=accessibility_assessment,
        )

    def _load_model(self, model_size: str | None = None, *, backend: CaptionBackend | None = None):
        selected_backend = backend or self._faster_whisper_backend
        try:
            model = selected_backend.load_model(model_size)
            self._models = getattr(selected_backend, "_models", {})
            return model
        except RuntimeError as exc:
            backend_label = _caption_backend_display_name(selected_backend)
            raise EnhancementRuntimeError(
                f"{backend_label} is required for this caption path. Install the missing runtime dependency in the helper environment."
            ) from exc

    def _evict_cached_models_except(self, keep_model_size: str) -> None:
        self._faster_whisper_backend._evict_cached_models_except(keep_model_size)
        self._models = self._faster_whisper_backend._models
        gc.collect()

    def _transcribe_file(
        self,
        model,
        audio_path: Path,
        *,
        preserve_fillers: bool,
        backend: CaptionBackend | None = None,
        model_size: str | None = None,
        beam_size: int | None = None,
        condition_on_previous_text: bool = False,
        initial_prompt: str | None = None,
    ):
        selected_backend = backend or self._faster_whisper_backend
        prompt_text = initial_prompt
        if preserve_fillers and not prompt_text:
            prompt_text = _AGGRESSIVE_FILLER_PROMPT
        if selected_backend.id == "whispercpp":
            return selected_backend.transcribe_chunk(
                audio_path,
                preserve_fillers=preserve_fillers,
                model_size=model_size,
                beam_size=beam_size,
                condition_on_previous_text=condition_on_previous_text,
                initial_prompt=prompt_text,
            )
        return selected_backend.transcribe_loaded_model(
            model,
            audio_path,
            preserve_fillers=preserve_fillers,
            beam_size=beam_size,
            condition_on_previous_text=condition_on_previous_text,
            initial_prompt=prompt_text,
        )

    def _transcribe_timeline(
        self,
        audio_path: Path,
        *,
        total_duration: float,
        started_at: float,
        cleanup_eta_seconds: int,
        on_stage: CleanupStageCallback | None,
        remove_filler_words: bool,
        filler_removal_mode: FillerRemovalMode,
        transcribe_detail: str = "Transcribing speech timing for cleanup.",
        cancel_check: Callable[[], bool] | None = None,
        force_windowed: bool = False,
        preserve_fillers: bool = False,
        backend: CaptionBackend | None = None,
        model_size: str | None = None,
        beam_size: int | None = None,
        condition_on_previous_text: bool = False,
        initial_prompt: str | None = None,
        window_seconds: float | None = None,
        overlap_seconds: float | None = None,
    ) -> tuple[list[TranscriptWordTiming], list[TranscriptSegmentTiming]]:
        normalized_mode = _normalize_filler_mode(filler_removal_mode)
        should_use_windowed = force_windowed or (remove_filler_words and normalized_mode == FillerRemovalMode.AGGRESSIVE)
        effective_beam_size = beam_size
        if should_use_windowed and preserve_fillers and effective_beam_size is None:
            effective_beam_size = 1
        if should_use_windowed:
            return self._transcribe_windowed_timeline(
                audio_path,
                total_duration=total_duration,
                started_at=started_at,
                cleanup_eta_seconds=cleanup_eta_seconds,
                on_stage=on_stage,
                transcribe_detail=transcribe_detail,
                cancel_check=cancel_check,
                preserve_fillers=preserve_fillers or (remove_filler_words and normalized_mode == FillerRemovalMode.AGGRESSIVE),
                backend=backend,
                model_size=model_size,
                beam_size=effective_beam_size,
                condition_on_previous_text=condition_on_previous_text,
                initial_prompt=initial_prompt,
                window_seconds=window_seconds,
                overlap_seconds=overlap_seconds,
            )

        if cancel_check and cancel_check():
            raise JobCancelledError("job cancelled")
        selected_backend = backend or self._faster_whisper_backend
        if selected_backend.id == "whispercpp":
            model = None
        elif selected_backend is self._faster_whisper_backend:
            model = self._load_model(model_size)
        else:
            model = self._load_model(model_size, backend=selected_backend)

        transcribe_kwargs = {
            "preserve_fillers": preserve_fillers,
            "beam_size": effective_beam_size,
            "condition_on_previous_text": condition_on_previous_text,
            "initial_prompt": initial_prompt,
        }
        if selected_backend is not self._faster_whisper_backend:
            transcribe_kwargs["backend"] = selected_backend
            transcribe_kwargs["model_size"] = model_size
        transcription = self._transcribe_file(model, audio_path, **transcribe_kwargs)
        words, segments = _collect_timing_rows(
            transcription,
            window_offset_seconds=0.0,
            keep_start_seconds=0.0,
            keep_end_seconds=max(total_duration, 0.0) if total_duration > 0 else float("inf"),
        )
        last_progress_emit_at = 0.0
        for seg in segments:
            if cancel_check and cancel_check():
                raise JobCancelledError("job cancelled")
            end = max(0.0, float(seg.end))
            if on_stage:
                now = time.monotonic()
                if (
                    last_progress_emit_at == 0.0
                    or now - last_progress_emit_at >= _TRANSCRIBE_PROGRESS_MIN_INTERVAL_SECONDS
                    or (total_duration > 0 and end >= total_duration - 0.2)
                ):
                    coverage = min(1.0, end / max(total_duration, 0.01))
                    progress = min(0.68, 0.08 + (coverage * 0.6))
                    on_stage(
                        progress,
                        transcribe_detail,
                        _transcription_eta_seconds(
                            elapsed_seconds=max(0.0, now - started_at),
                            cleanup_eta_seconds=cleanup_eta_seconds,
                            coverage=coverage,
                        ),
                    )
                    last_progress_emit_at = now
        return words, segments

    def _transcribe_windowed_timeline(
        self,
        audio_path: Path,
        *,
        total_duration: float,
        started_at: float,
        cleanup_eta_seconds: int,
        on_stage: CleanupStageCallback | None,
        transcribe_detail: str = "Transcribing speech timing for cleanup.",
        cancel_check: Callable[[], bool] | None = None,
        preserve_fillers: bool = False,
        backend: CaptionBackend | None = None,
        model_size: str | None = None,
        beam_size: int | None = None,
        condition_on_previous_text: bool = False,
        initial_prompt: str | None = None,
        window_seconds: float | None = None,
        overlap_seconds: float | None = None,
    ) -> tuple[list[TranscriptWordTiming], list[TranscriptSegmentTiming]]:
        if cancel_check and cancel_check():
            raise JobCancelledError("job cancelled")
        selected_backend = backend or self._faster_whisper_backend
        if selected_backend.id == "whispercpp":
            model = None
        elif selected_backend is self._faster_whisper_backend:
            model = self._load_model(model_size)
        else:
            model = self._load_model(model_size, backend=selected_backend)
        waveform, sample_rate = _read_pcm16_wav(audio_path)
        total_duration = max(0.0, float(total_duration))
        if total_duration <= 0.0:
            return [], []

        resolved_window_seconds = min(max(float(window_seconds or _AGGRESSIVE_TRANSCRIBE_WINDOW_SECONDS), 1.0), total_duration)
        resolved_overlap_seconds = min(float(overlap_seconds or _AGGRESSIVE_TRANSCRIBE_OVERLAP_SECONDS), max(0.0, resolved_window_seconds / 2.0))
        step_seconds = max(0.5, resolved_window_seconds - resolved_overlap_seconds)
        words: list[TranscriptWordTiming] = []
        segments: list[TranscriptSegmentTiming] = []

        with tempfile.TemporaryDirectory(prefix="radcast_cleanup_transcribe_") as tmp:
            tmp_path = Path(tmp)
            window_start = 0.0
            window_index = 0
            total_windows = max(1, int(math.ceil(max(total_duration - resolved_window_seconds, 0.0) / step_seconds)) + 1)
            while True:
                if cancel_check and cancel_check():
                    raise JobCancelledError("job cancelled")
                window_end = min(total_duration, window_start + resolved_window_seconds)
                start_idx = max(0, min(len(waveform), int(round(window_start * sample_rate))))
                end_idx = max(start_idx, min(len(waveform), int(round(window_end * sample_rate))))
                window_path = tmp_path / f"window_{int(round(window_start * 1000)):06d}.wav"
                _write_pcm16_wav(window_path, waveform[start_idx:end_idx], sample_rate=sample_rate)
                transcribe_kwargs = {
                    "preserve_fillers": preserve_fillers,
                    "beam_size": beam_size,
                    "condition_on_previous_text": condition_on_previous_text,
                    "initial_prompt": initial_prompt,
                }
                if selected_backend is not self._faster_whisper_backend:
                    transcribe_kwargs["backend"] = selected_backend
                    transcribe_kwargs["model_size"] = model_size
                transcribed_segments = self._transcribe_file(model, window_path, **transcribe_kwargs)

                left_guard_seconds = 0.0 if window_index == 0 else resolved_overlap_seconds / 2.0
                right_guard_seconds = 0.0 if window_end >= total_duration - 1e-6 else resolved_overlap_seconds / 2.0
                keep_start_seconds = left_guard_seconds
                keep_end_seconds = max(keep_start_seconds, (window_end - window_start) - right_guard_seconds)
                window_words, window_segments = _collect_timing_rows(
                    transcribed_segments,
                    window_offset_seconds=window_start,
                    keep_start_seconds=keep_start_seconds,
                    keep_end_seconds=keep_end_seconds,
                )
                words.extend(window_words)
                segments.extend(window_segments)

                if on_stage:
                    coverage = min(1.0, window_end / max(total_duration, 0.01))
                    progress = min(0.68, 0.08 + (coverage * 0.6))
                    processed_windows = min(total_windows, window_index + 1)
                    on_stage(
                        progress,
                        _windowed_stage_detail(
                            transcribe_detail,
                            current_window=processed_windows,
                            total_windows=total_windows,
                        ),
                        _windowed_transcription_eta_seconds(
                            elapsed_seconds=max(0.0, time.monotonic() - started_at),
                            cleanup_eta_seconds=cleanup_eta_seconds,
                            processed_windows=processed_windows,
                            total_windows=total_windows,
                            coverage=coverage,
                        ),
                    )

                if window_end >= total_duration - 1e-6:
                    break
                window_start = min(total_duration, window_start + step_seconds)
                window_index += 1

        return _dedupe_transcript_words(words), _dedupe_transcript_segments(segments)

    def _caption_profile_for_mode(
        self,
        caption_quality_mode: CaptionQualityMode,
        *,
        caption_prompt: str | None,
    ) -> CaptionTranscriptionProfile:
        policy = self.caption_quality_policy_for_mode(caption_quality_mode)
        if caption_quality_mode == CaptionQualityMode.FAST:
            return CaptionTranscriptionProfile(
                model_size=policy.first_pass_model_size,
                beam_size=policy.first_pass_beam_size,
                window_seconds=_CAPTION_FAST_WINDOW_SECONDS,
                overlap_seconds=_CAPTION_FAST_OVERLAP_SECONDS,
                condition_on_previous_text=False,
                initial_prompt=caption_prompt,
            )
        if caption_quality_mode == CaptionQualityMode.REVIEWED:
            return CaptionTranscriptionProfile(
                model_size=policy.first_pass_model_size,
                beam_size=policy.first_pass_beam_size,
                window_seconds=_CAPTION_REVIEWED_WINDOW_SECONDS,
                overlap_seconds=_CAPTION_REVIEWED_OVERLAP_SECONDS,
                condition_on_previous_text=True,
                initial_prompt=caption_prompt,
                review_sweep=True,
            )
        return CaptionTranscriptionProfile(
            model_size=policy.first_pass_model_size,
            beam_size=policy.first_pass_beam_size,
            window_seconds=_CAPTION_ACCURATE_WINDOW_SECONDS,
            overlap_seconds=_CAPTION_ACCURATE_OVERLAP_SECONDS,
            condition_on_previous_text=True,
            initial_prompt=caption_prompt,
        )

    def _review_and_correct_caption_segments(
        self,
        *,
        analysis_wav: Path,
        base_segments: list[TranscriptSegmentTiming],
        quality_report: CaptionQualityReport,
        prompt_text: str | None,
        on_stage: CleanupStageCallback | None = None,
        started_at: float | None = None,
        caption_eta_seconds: int | None = None,
        review_backend: CaptionBackend | None = None,
        review_model_size: str | None = None,
        progress_label: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> list[TranscriptSegmentTiming]:
        if not quality_report.flagged_segments:
            return base_segments
        selected_backend = review_backend or self._faster_whisper_backend
        resolved_review_model_size = str(review_model_size or self.caption_reviewed_model_size).strip() or self.caption_reviewed_model_size
        if selected_backend.id == "whispercpp":
            model = None
        else:
            model = self._load_model(resolved_review_model_size, backend=selected_backend)
        waveform, sample_rate = _read_pcm16_wav(analysis_wav)
        corrected = list(base_segments)
        flags = quality_report.flagged_segments
        total_flags = len(flags)
        review_started_at = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="radcast_caption_review_") as tmp:
            tmp_path = Path(tmp)
            for flag_index, flag in enumerate(flags, start=1):
                if cancel_check and cancel_check():
                    raise JobCancelledError("job cancelled")
                review_detail = _caption_stage_detail(
                    action="Reviewing low-confidence caption lines",
                    backend=selected_backend,
                    model_size=resolved_review_model_size,
                )
                if progress_label:
                    review_detail = f"{progress_label}: {review_detail}"
                if on_stage:
                    on_stage(
                        0.82 + (((flag_index - 1) / max(1, total_flags)) * 0.08),
                        _indexed_stage_detail(
                            review_detail,
                            current_item=flag_index,
                            total_items=total_flags,
                        ),
                        _review_sweep_eta_seconds(
                            elapsed_seconds=max(0.0, time.monotonic() - review_started_at),
                            processed_flags=flag_index - 1,
                            total_flags=total_flags,
                        ),
                    )
                matched_index = _find_segment_index(corrected, flag)
                if matched_index is None:
                    continue
                candidate_segment = self._review_caption_flag(
                    model=model,
                    waveform=waveform,
                    sample_rate=sample_rate,
                    flag=flag,
                    prompt_text=prompt_text,
                    tmp_path=tmp_path,
                    review_backend=selected_backend,
                    review_model_size=resolved_review_model_size,
                )
                if candidate_segment is None:
                    continue
                current_segment = corrected[matched_index]
                current_probability = current_segment.average_probability if current_segment.average_probability is not None else -1.0
                next_probability = candidate_segment.average_probability if candidate_segment.average_probability is not None else current_probability
                if next_probability + 0.03 < current_probability and not _should_accept_truncation_review_candidate(
                    flag=flag,
                    current_segment=current_segment,
                    candidate_segment=candidate_segment,
                ):
                    continue
                corrected[matched_index] = candidate_segment
                if on_stage:
                    elapsed = max(0.0, time.monotonic() - review_started_at)
                    overall_elapsed = max(0.0, time.monotonic() - float(started_at or review_started_at))
                    on_stage(
                        0.82 + ((flag_index / max(1, total_flags)) * 0.08),
                        _indexed_stage_detail(
                            review_detail,
                            current_item=flag_index,
                            total_items=total_flags,
                        ),
                        _review_sweep_eta_seconds(
                            elapsed_seconds=elapsed,
                            processed_flags=flag_index,
                            total_flags=total_flags,
                        )
                        or _remaining_cleanup_eta(float(started_at or review_started_at), int(caption_eta_seconds or max(30, int(overall_elapsed + 8))), floor_seconds=4),
                    )
        return corrected

    def _review_caption_flag(
        self,
        *,
        model,
        waveform: np.ndarray,
        sample_rate: int,
        flag: CaptionReviewFlag,
        prompt_text: str | None,
        tmp_path: Path,
        review_backend: CaptionBackend | None = None,
        review_model_size: str | None = None,
    ) -> TranscriptSegmentTiming | None:
        snippet_start = max(0.0, flag.start - _CAPTION_REVIEW_SWEEP_CONTEXT_SECONDS)
        snippet_end = max(snippet_start + 0.5, flag.end + _CAPTION_REVIEW_SWEEP_CONTEXT_SECONDS)
        total_duration = waveform.shape[0] / float(sample_rate) if sample_rate else 0.0
        snippet_end = min(total_duration, snippet_end)
        start_idx = max(0, min(len(waveform), int(round(snippet_start * sample_rate))))
        end_idx = max(start_idx, min(len(waveform), int(round(snippet_end * sample_rate))))
        if end_idx <= start_idx:
            return None
        snippet_path = tmp_path / f"caption_review_{int(round(flag.start * 1000))}.wav"
        _write_pcm16_wav(snippet_path, waveform[start_idx:end_idx], sample_rate=sample_rate)
        selected_backend = review_backend or self._faster_whisper_backend
        review_segments = self._transcribe_file(
            model,
            snippet_path,
            preserve_fillers=False,
            beam_size=self.caption_reviewed_beam_size,
            condition_on_previous_text=True,
            initial_prompt=_combine_prompt_parts(prompt_text, _CAPTION_REVIEW_PROMPT),
            backend=selected_backend,
            model_size=review_model_size,
        )
        _, candidate_segments = _collect_timing_rows(
            review_segments,
            window_offset_seconds=snippet_start,
            keep_start_seconds=0.0,
            keep_end_seconds=max(0.0, snippet_end - snippet_start),
        )
        best = _best_review_candidate(candidate_segments, flag)
        if best is None:
            return None
        if not _clean_caption_text(best.text):
            return None
        candidate_text = sanitize_review_candidate_text(best.text, reference_text=flag.text)
        if not candidate_text:
            return None
        if _clean_caption_text(candidate_text) == _clean_caption_text(flag.text) and (
            best.average_probability is None
            or (flag.average_probability is not None and best.average_probability <= flag.average_probability + 0.01)
        ):
            return None
        return TranscriptSegmentTiming(
            text=candidate_text,
            start=flag.start,
            end=max(flag.end, flag.start + 0.2),
            average_probability=best.average_probability,
        )

    def _filler_intervals(
        self,
        *,
        words: list[TranscriptWordTiming],
        remove_filler_words: bool,
        filler_removal_mode: FillerRemovalMode,
    ) -> tuple[list[tuple[float, float]], int]:
        if not remove_filler_words or not words:
            return [], 0

        heuristics = _filler_heuristics_for_mode(filler_removal_mode)
        intervals: list[tuple[float, float]] = []
        count = 0
        idx = 0
        while idx < len(words):
            word = words[idx]
            normalized = _normalize_token(word.text)
            if not _is_filler_token(normalized):
                idx += 1
                continue

            run_words, next_idx = _collect_filler_run(words, idx, heuristics=heuristics)
            run_start = run_words[0].start
            run_end = run_words[-1].end
            duration = max(0.0, run_end - run_start)
            if duration < _FILLER_MIN_DURATION_SECONDS or duration > _FILLER_MAX_DURATION_SECONDS:
                idx = next_idx
                continue
            if not _filler_run_confident_enough(run_words, heuristics=heuristics):
                idx = next_idx
                continue

            prev_end = words[idx - 1].end if idx > 0 else 0.0
            next_start = words[next_idx].start if next_idx < len(words) else run_end
            gap_before = max(0.0, run_start - prev_end)
            gap_after = max(0.0, next_start - run_end)

            if not _filler_has_enough_context(gap_before, gap_after, heuristics=heuristics):
                idx = next_idx
                continue

            lead_pad = min(heuristics.lead_pad_cap_seconds, gap_before * heuristics.lead_pad_ratio)
            tail_pad = min(heuristics.tail_pad_cap_seconds, gap_after * heuristics.tail_pad_ratio)
            intervals.append((max(0.0, run_start - lead_pad), max(run_start, run_end + tail_pad)))
            count += len(run_words)
            idx = next_idx
        return intervals, count

    def _silence_intervals(
        self,
        *,
        words: list[TranscriptWordTiming],
        segments: list[TranscriptSegmentTiming],
        total_duration: float,
        max_silence_seconds: float | None,
        treat_fillers_as_removed: bool,
    ) -> tuple[list[tuple[float, float]], int]:
        if max_silence_seconds is None:
            return [], 0

        speech_intervals = self._speech_intervals_for_compaction(
            words=words,
            segments=segments,
            treat_fillers_as_removed=treat_fillers_as_removed,
        )
        if not speech_intervals:
            return [], 0

        keep_seconds = max(0.0, float(max_silence_seconds))
        trigger_seconds = max(_MIN_COMPACTABLE_GAP_SECONDS, keep_seconds)
        intervals: list[tuple[float, float]] = []
        count = 0
        cursor = 0.0
        for start, end in speech_intervals:
            gap_start = cursor
            gap_end = max(cursor, start)
            gap_duration = max(0.0, gap_end - gap_start)
            if gap_duration > trigger_seconds:
                trim_from = min(gap_end, gap_start + keep_seconds)
                if trim_from < gap_end:
                    intervals.append((trim_from, gap_end))
                    count += 1
            cursor = max(cursor, end)

        trailing_gap = max(0.0, total_duration - cursor)
        if trailing_gap > trigger_seconds:
            trim_from = min(total_duration, cursor + keep_seconds)
            if trim_from < total_duration:
                intervals.append((trim_from, total_duration))
                count += 1
        return intervals, count

    def _speech_intervals_for_compaction(
        self,
        *,
        words: list[TranscriptWordTiming],
        segments: list[TranscriptSegmentTiming],
        treat_fillers_as_removed: bool,
    ) -> list[tuple[float, float]]:
        if words:
            raw_intervals: list[tuple[float, float]] = []
            for word in words:
                normalized = _normalize_token(word.text)
                if treat_fillers_as_removed and _is_filler_token(normalized):
                    continue
                if word.end > word.start:
                    raw_intervals.append((word.start, word.end))
            if raw_intervals:
                return _merge_touching_intervals(raw_intervals)

        raw_segments = [(segment.start, segment.end) for segment in segments if segment.end > segment.start]
        return _merge_touching_intervals(raw_segments)

    @staticmethod
    def _rewrite_detail(*, silence_count: int, filler_count: int) -> str:
        parts: list[str] = []
        if silence_count > 0:
            parts.append(f"shortening {silence_count} long pause{'s' if silence_count != 1 else ''}")
        if filler_count > 0:
            parts.append(f"removing {filler_count} filler word{'s' if filler_count != 1 else ''}")
        if not parts:
            return "No extra speech cleanup was needed."
        return "Applying speech cleanup: " + ", ".join(parts) + "."


def _normalize_token(text: str) -> str:
    cleaned = _TOKEN_RE.sub("", str(text or "").strip().lower())
    return cleaned.strip("'")


def _combine_prompt_parts(*parts: str | None) -> str | None:
    cleaned_parts = [str(part).strip() for part in parts if str(part or "").strip()]
    if not cleaned_parts:
        return None
    return " ".join(cleaned_parts)


def _build_caption_prompt(custom_glossary: str | None) -> str:
    glossary_terms = _normalize_custom_glossary(custom_glossary)
    prompt_parts = [_NZ_ENGLISH_STYLE_PROMPT, _MAORI_GLOSSARY_PROMPT]
    if glossary_terms:
        prompt_parts.append(
            "Also prefer these course or project terms if spoken clearly: " + ", ".join(glossary_terms) + "."
        )
    return _combine_prompt_parts(*prompt_parts) or _NZ_ENGLISH_STYLE_PROMPT


def _critical_caption_terms(custom_glossary: str | None) -> list[str]:
    glossary_terms = _normalize_custom_glossary(custom_glossary)
    combined: list[str] = []
    seen: set[str] = set()
    for term in [*glossary_terms, *_COMMON_MAORI_TERMS]:
        normalized = " ".join(str(term or "").split()).strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        combined.append(normalized)
    return combined


def _normalize_custom_glossary(value: str | None) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    parts = re.split(r"[\n,;|]+", raw)
    normalized: list[str] = []
    seen: set[str] = set()
    for part in parts:
        term = " ".join(part.split()).strip()
        if not term:
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(term[:80])
        if len(normalized) >= 60:
            break
    return normalized


def _is_filler_token(normalized: str) -> bool:
    if normalized in _FILLER_WORDS:
        return True
    if not normalized:
        return False
    return bool(
        re.fullmatch(r"u+m+", normalized)
        or re.fullmatch(r"u+h+", normalized)
        or re.fullmatch(r"u+h+m+", normalized)
        or re.fullmatch(r"e+r+m+", normalized)
        or re.fullmatch(r"a+h+", normalized)
    )


def _normalize_filler_mode(value: FillerRemovalMode | str | None) -> FillerRemovalMode:
    if isinstance(value, FillerRemovalMode):
        return value
    try:
        return FillerRemovalMode(str(value or FillerRemovalMode.AGGRESSIVE.value).strip().lower())
    except ValueError:
        return FillerRemovalMode.AGGRESSIVE


def _normalize_caption_quality_mode(value: CaptionQualityMode | str | None) -> CaptionQualityMode:
    if isinstance(value, CaptionQualityMode):
        return value
    try:
        return CaptionQualityMode(str(value or CaptionQualityMode.REVIEWED.value).strip().lower())
    except ValueError:
        return CaptionQualityMode.REVIEWED


def _filler_heuristics_for_mode(mode: FillerRemovalMode | str | None) -> FillerRemovalHeuristics:
    normalized_mode = _normalize_filler_mode(mode)
    if normalized_mode == FillerRemovalMode.NORMAL:
        return _NORMAL_FILLER_HEURISTICS
    return _AGGRESSIVE_FILLER_HEURISTICS


def _filler_has_enough_context(gap_before: float, gap_after: float, *, heuristics: FillerRemovalHeuristics) -> bool:
    total_gap = max(0.0, gap_before) + max(0.0, gap_after)
    strongest_gap = max(gap_before, gap_after)
    if total_gap >= heuristics.min_context_gap_seconds and strongest_gap >= heuristics.min_strong_side_gap_seconds:
        return True
    if (
        total_gap >= heuristics.two_sided_context_gap_seconds
        and gap_before >= heuristics.two_sided_min_gap_seconds
        and gap_after >= heuristics.two_sided_min_gap_seconds
    ):
        return True
    return strongest_gap >= heuristics.single_side_gap_seconds


def _collect_filler_run(
    words: list[TranscriptWordTiming],
    start_idx: int,
    *,
    heuristics: FillerRemovalHeuristics,
) -> tuple[list[TranscriptWordTiming], int]:
    run_words = [words[start_idx]]
    next_idx = start_idx + 1
    while next_idx < len(words):
        next_word = words[next_idx]
        normalized = _normalize_token(next_word.text)
        if not _is_filler_token(normalized):
            break
        if max(0.0, next_word.start - run_words[-1].end) > heuristics.run_max_internal_gap_seconds:
            break
        run_words.append(next_word)
        next_idx += 1
    return run_words, next_idx


def _filler_run_confident_enough(words: list[TranscriptWordTiming], *, heuristics: FillerRemovalHeuristics) -> bool:
    if heuristics.always_accept_explicit_fillers and all(_is_filler_token(_normalize_token(word.text)) for word in words):
        return True
    probabilities = [float(word.probability) for word in words if word.probability is not None]
    if not probabilities:
        return True
    average_probability = sum(probabilities) / len(probabilities)
    strongest_probability = max(probabilities)
    return average_probability >= heuristics.min_probability or strongest_probability >= heuristics.strong_probability


def _remaining_cleanup_eta(started_at: float, cleanup_eta_seconds: int, *, floor_seconds: int) -> int:
    elapsed_seconds = max(0.0, time.monotonic() - started_at)
    return max(int(floor_seconds), int(round(max(1.0, cleanup_eta_seconds - elapsed_seconds))))


def _transcription_eta_seconds(*, elapsed_seconds: float, cleanup_eta_seconds: int, coverage: float) -> int:
    safe_elapsed = max(0.0, float(elapsed_seconds))
    safe_coverage = max(0.0, min(1.0, float(coverage)))
    if safe_coverage >= 0.08:
        projected_total = max(float(cleanup_eta_seconds), safe_elapsed / safe_coverage)
        if safe_coverage < 0.35:
            projected_total *= 1.24
        elif safe_coverage < 0.65:
            projected_total *= 1.16
        elif safe_coverage < 0.88:
            projected_total *= 1.1
        elif safe_coverage < 0.97:
            projected_total *= 1.06
        remaining = projected_total - safe_elapsed
    else:
        remaining = (float(cleanup_eta_seconds) - safe_elapsed) * 1.15
    if safe_coverage < 0.8:
        floor_seconds = 12
    elif safe_coverage < 0.94:
        floor_seconds = 8
    elif safe_coverage < 0.985:
        floor_seconds = 5
    else:
        floor_seconds = 2
    return max(floor_seconds, int(round(max(1.0, remaining))))


def _windowed_transcription_eta_seconds(
    *,
    elapsed_seconds: float,
    cleanup_eta_seconds: int,
    processed_windows: int,
    total_windows: int,
    coverage: float,
) -> int | None:
    safe_processed_windows = max(1, int(processed_windows))
    safe_total_windows = max(safe_processed_windows, int(total_windows))
    if safe_processed_windows < 3 and safe_total_windows > 1:
        return None
    remaining_windows = max(0, safe_total_windows - safe_processed_windows)
    average_window_seconds = max(1.0, float(elapsed_seconds) / safe_processed_windows)
    window_projection = remaining_windows * average_window_seconds
    remaining = window_projection
    progress_ratio = safe_processed_windows / safe_total_windows
    if progress_ratio < 0.35:
        remaining *= 1.12
    elif progress_ratio < 0.55:
        remaining *= 1.08
    elif progress_ratio < 0.8:
        remaining *= 1.04
    remaining += 6.0
    if remaining_windows >= 6:
        floor_seconds = 24
    elif remaining_windows >= 3:
        floor_seconds = 14
    elif remaining_windows >= 1:
        floor_seconds = 8
    else:
        floor_seconds = 3
    return max(floor_seconds, int(round(max(1.0, remaining))))


def _review_sweep_eta_seconds(
    *,
    elapsed_seconds: float,
    processed_flags: int,
    total_flags: int,
) -> int | None:
    safe_total_flags = max(1, int(total_flags))
    safe_processed_flags = max(0, int(processed_flags))
    if safe_processed_flags < 1:
        return None
    remaining_flags = max(0, safe_total_flags - safe_processed_flags)
    average_flag_seconds = max(1.0, float(elapsed_seconds) / safe_processed_flags)
    remaining = (remaining_flags * average_flag_seconds) + 4.0
    if remaining_flags >= 6:
        floor_seconds = 18
    elif remaining_flags >= 3:
        floor_seconds = 10
    elif remaining_flags >= 1:
        floor_seconds = 5
    else:
        floor_seconds = 2
    return max(floor_seconds, int(round(max(1.0, remaining))))


def _collect_timing_rows(
    transcribed_segments: CaptionTranscriptionResult | list[object],
    *,
    window_offset_seconds: float,
    keep_start_seconds: float,
    keep_end_seconds: float,
) -> tuple[list[TranscriptWordTiming], list[TranscriptSegmentTiming]]:
    words: list[TranscriptWordTiming] = []
    segments: list[TranscriptSegmentTiming] = []
    if isinstance(transcribed_segments, CaptionTranscriptionResult):
        source_segments = transcribed_segments.segments
        for seg in source_segments:
            seg_start = max(0.0, float(seg.start))
            seg_end = max(seg_start, float(seg.end))
            if seg_end <= keep_start_seconds or seg_start >= keep_end_seconds:
                continue
            text = str(seg.text or "").strip()
            segment_probabilities: list[float] = []
            segment_words: list[str] = []
            segments.append(
                TranscriptSegmentTiming(
                    text=text,
                    start=window_offset_seconds + max(seg_start, keep_start_seconds),
                    end=window_offset_seconds + min(seg_end, keep_end_seconds),
                )
            )
            for word in seg.words or ():
                word_start = max(0.0, float(word.start))
                word_end = max(word_start, float(word.end))
                if word_end <= keep_start_seconds or word_start >= keep_end_seconds:
                    continue
                probability = float(word.probability) if word.probability is not None else None
                if probability is not None:
                    segment_probabilities.append(probability)
                token_text = str(word.text or "").strip()
                if token_text:
                    segment_words.append(token_text)
                words.append(
                    TranscriptWordTiming(
                        text=token_text,
                        start=window_offset_seconds + max(word_start, keep_start_seconds),
                        end=window_offset_seconds + min(word_end, keep_end_seconds),
                        probability=probability,
                    )
                )
            segment_text = " ".join(segment_words).strip() or text
            segments[-1] = TranscriptSegmentTiming(
                text=segment_text,
                start=segments[-1].start,
                end=segments[-1].end,
                average_probability=(sum(segment_probabilities) / len(segment_probabilities)) if segment_probabilities else None,
            )
        return words, segments

    for seg in transcribed_segments:
        seg_start = max(0.0, float(seg.start))
        seg_end = max(seg_start, float(seg.end))
        if seg_end <= keep_start_seconds or seg_start >= keep_end_seconds:
            continue
        text = str(seg.text or "").strip()
        segment_probabilities: list[float] = []
        segment_words: list[str] = []
        segments.append(
            TranscriptSegmentTiming(
                text=text,
                start=window_offset_seconds + max(seg_start, keep_start_seconds),
                end=window_offset_seconds + min(seg_end, keep_end_seconds),
            )
        )
        for word in seg.words or []:
            word_start = max(0.0, float(word.start))
            word_end = max(word_start, float(word.end))
            if word_end <= keep_start_seconds or word_start >= keep_end_seconds:
                continue
            probability = float(word.probability) if word.probability is not None else None
            if probability is not None:
                segment_probabilities.append(probability)
            token_text = str(word.word or "").strip()
            if token_text:
                segment_words.append(token_text)
            words.append(
                TranscriptWordTiming(
                    text=token_text,
                    start=window_offset_seconds + max(word_start, keep_start_seconds),
                    end=window_offset_seconds + min(word_end, keep_end_seconds),
                    probability=probability,
                )
            )
        segment_text = " ".join(segment_words).strip() or text
        segments[-1] = TranscriptSegmentTiming(
            text=segment_text,
            start=segments[-1].start,
            end=segments[-1].end,
            average_probability=(sum(segment_probabilities) / len(segment_probabilities)) if segment_probabilities else None,
        )
    return words, segments


def _dedupe_transcript_words(words: list[TranscriptWordTiming]) -> list[TranscriptWordTiming]:
    if not words:
        return []
    deduped: list[TranscriptWordTiming] = []
    for word in sorted(words, key=lambda item: (item.start, item.end, item.text.lower())):
        if not deduped:
            deduped.append(word)
            continue
        prev = deduped[-1]
        same_token = _normalize_token(prev.text) == _normalize_token(word.text)
        same_window = abs(prev.start - word.start) <= 0.08 and abs(prev.end - word.end) <= 0.12
        if same_token and same_window:
            prev_probability = prev.probability if prev.probability is not None else -1.0
            word_probability = word.probability if word.probability is not None else -1.0
            if word_probability > prev_probability:
                deduped[-1] = word
            continue
        deduped.append(word)
    return deduped


def _dedupe_transcript_segments(segments: list[TranscriptSegmentTiming]) -> list[TranscriptSegmentTiming]:
    if not segments:
        return []
    deduped: list[TranscriptSegmentTiming] = []
    for segment in sorted(segments, key=lambda item: (item.start, item.end, item.text.lower())):
        if not deduped:
            deduped.append(segment)
            continue
        prev = deduped[-1]
        same_text = prev.text.strip().lower() == segment.text.strip().lower()
        same_window = abs(prev.start - segment.start) <= 0.08 and abs(prev.end - segment.end) <= 0.12
        if same_text and same_window:
            continue
        deduped.append(segment)
    return deduped


def _dedupe_caption_segments(segments: list[TranscriptSegmentTiming]) -> list[TranscriptSegmentTiming]:
    if not segments:
        return []
    deduped: list[TranscriptSegmentTiming] = []
    for segment in sorted(segments, key=lambda item: (item.start, item.end, item.text.lower())):
        cleaned_text = _clean_caption_text(segment.text)
        candidate = TranscriptSegmentTiming(
            text=cleaned_text or segment.text,
            start=segment.start,
            end=segment.end,
            average_probability=segment.average_probability,
        )
        if not deduped:
            deduped.append(candidate)
            continue
        previous = deduped[-1]
        if _caption_segments_look_duplicate(previous, candidate):
            deduped[-1] = _preferred_caption_segment(previous, candidate)
            continue
        deduped.append(candidate)
    return deduped


def _caption_segments_look_duplicate(first: TranscriptSegmentTiming, second: TranscriptSegmentTiming) -> bool:
    first_text = _clean_caption_text(first.text).lower()
    second_text = _clean_caption_text(second.text).lower()
    if not first_text or not second_text:
        return False
    overlap_ratio = _segment_overlap(first.start, first.end, second.start, second.end)
    gap_seconds = max(0.0, second.start - first.end)
    if overlap_ratio <= 0.0 and gap_seconds > 0.3:
        return False
    if first_text == second_text:
        return overlap_ratio >= 0.08 or gap_seconds <= 0.22

    shorter_text, longer_text = (first_text, second_text) if len(first_text) <= len(second_text) else (second_text, first_text)
    if len(shorter_text) >= 12 and shorter_text in longer_text:
        return overlap_ratio >= 0.06 or gap_seconds <= 0.18

    first_tokens = _caption_tokens(first_text)
    second_tokens = _caption_tokens(second_text)
    if min(len(first_tokens), len(second_tokens)) < 3:
        return False
    shared_ratio = _caption_shared_token_ratio(first_tokens, second_tokens)
    return shared_ratio >= 0.8 and (overlap_ratio >= 0.08 or gap_seconds <= 0.14)


def _preferred_caption_segment(first: TranscriptSegmentTiming, second: TranscriptSegmentTiming) -> TranscriptSegmentTiming:
    first_text = _clean_caption_text(first.text)
    second_text = _clean_caption_text(second.text)
    if len(second_text) > len(first_text) + 4:
        return second
    if len(first_text) > len(second_text) + 4:
        return first
    first_probability = first.average_probability if first.average_probability is not None else -1.0
    second_probability = second.average_probability if second.average_probability is not None else -1.0
    if second_probability > first_probability + 0.03:
        return second
    if first_probability > second_probability + 0.03:
        return first
    first_duration = max(0.0, first.end - first.start)
    second_duration = max(0.0, second.end - second.start)
    if second_duration > first_duration + 0.12:
        return second
    return first


def _caption_tokens(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.split(text.lower()) if token]


def _caption_shared_token_ratio(first_tokens: list[str], second_tokens: list[str]) -> float:
    if not first_tokens or not second_tokens:
        return 0.0
    first_set = set(first_tokens)
    second_set = set(second_tokens)
    shared = len(first_set & second_set)
    return shared / max(1, min(len(first_set), len(second_set)))


def _merge_touching_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not intervals:
        return []
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if not merged:
            merged.append((start, end))
            continue
        prev_start, prev_end = merged[-1]
        if start <= prev_end + 0.06:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not intervals:
        return []
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        safe_start = max(0.0, float(start))
        safe_end = max(safe_start, float(end))
        if safe_end <= safe_start:
            continue
        if not merged:
            merged.append((safe_start, safe_end))
            continue
        prev_start, prev_end = merged[-1]
        if safe_start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, safe_end))
        else:
            merged.append((safe_start, safe_end))
    return merged


def _read_pcm16_wav(path: Path) -> tuple[np.ndarray, int]:
    try:
        with wave.open(str(path), "rb") as handle:
            sample_rate = handle.getframerate()
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            frames = handle.readframes(handle.getnframes())
    except wave.Error:
        return _read_wav_with_soundfile(path)
    if sample_width != 2:
        return _read_wav_with_soundfile(path)
    pcm = np.frombuffer(frames, dtype="<i2").astype(np.float32)
    if channels > 1:
        pcm = pcm.reshape(-1, channels)
    else:
        pcm = pcm.reshape(-1, 1)
    return pcm / 32768.0, sample_rate


def _read_wav_with_soundfile(path: Path) -> tuple[np.ndarray, int]:
    try:
        import soundfile as sf
    except ImportError as exc:  # pragma: no cover - dependency should already be installed
        raise EnhancementRuntimeError(
            "Speech cleanup could not read this WAV variant. Install soundfile or regenerate the helper audio."
        ) from exc
    try:
        samples, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception as exc:  # pragma: no cover - surfaced as runtime error
        raise EnhancementRuntimeError(f"Speech cleanup could not read analysis WAV: {exc}") from exc
    return np.asarray(samples, dtype=np.float32), int(sample_rate)


def _write_pcm16_wav(path: Path, samples: np.ndarray, *, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if samples.ndim == 1:
        samples = samples.reshape(-1, 1)
    clipped = np.clip(samples, -1.0, 1.0 - (1.0 / 32768.0))
    pcm = np.round(clipped * 32767.0).astype("<i2")
    channels = int(pcm.shape[1]) if pcm.ndim == 2 else 1
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(pcm.reshape(-1).tobytes())


def _splice_waveform(
    samples: np.ndarray,
    *,
    sample_rate: int,
    removal_intervals: list[tuple[float, float]],
) -> np.ndarray:
    total_samples = int(samples.shape[0])
    if total_samples <= 0 or not removal_intervals:
        return samples.copy()

    removals: list[tuple[int, int]] = []
    for start_seconds, end_seconds in removal_intervals:
        start_idx = max(0, min(total_samples, int(round(start_seconds * sample_rate))))
        end_idx = max(start_idx, min(total_samples, int(round(end_seconds * sample_rate))))
        if end_idx > start_idx:
            removals.append((start_idx, end_idx))
    if not removals:
        return samples.copy()

    keep_ranges: list[tuple[int, int]] = []
    cursor = 0
    for start_idx, end_idx in removals:
        if start_idx > cursor:
            keep_ranges.append((cursor, start_idx))
        cursor = max(cursor, end_idx)
    if cursor < total_samples:
        keep_ranges.append((cursor, total_samples))
    if not keep_ranges:
        return np.zeros((0, samples.shape[1]), dtype=np.float32)

    chunks = [samples[start:end].copy() for start, end in keep_ranges if end > start]
    if not chunks:
        return np.zeros((0, samples.shape[1]), dtype=np.float32)

    crossfade_samples = max(1, int(round(_CUT_CROSSFADE_SECONDS * sample_rate)))
    result = chunks[0]
    for chunk in chunks[1:]:
        overlap = min(crossfade_samples, result.shape[0], chunk.shape[0])
        if overlap <= 0:
            result = np.concatenate([result, chunk], axis=0)
            continue
        fade_out = np.linspace(1.0, 0.0, overlap, dtype=np.float32).reshape(-1, 1)
        fade_in = 1.0 - fade_out
        blended = (result[-overlap:] * fade_out) + (chunk[:overlap] * fade_in)
        result = np.concatenate([result[:-overlap], blended, chunk[overlap:]], axis=0)
    return result


def _find_segment_index(segments: list[TranscriptSegmentTiming], flag: CaptionReviewFlag) -> int | None:
    best_index = None
    best_score = -1.0
    for index, segment in enumerate(segments):
        score = _segment_overlap(segment.start, segment.end, flag.start, flag.end)
        if score <= 0:
            continue
        if score > best_score:
            best_index = index
            best_score = score
    return best_index


def _best_overlapping_segment(
    segments: list[TranscriptSegmentTiming],
    flag: CaptionReviewFlag,
) -> TranscriptSegmentTiming | None:
    best_segment = None
    best_score = -1.0
    for segment in segments:
        score = _segment_overlap(segment.start, segment.end, flag.start, flag.end)
        if score <= 0:
            continue
        probability = segment.average_probability if segment.average_probability is not None else 0.0
        adjusted_score = score + (probability * 0.15)
        if adjusted_score > best_score:
            best_segment = segment
            best_score = adjusted_score
    return best_segment


def _best_review_candidate(
    segments: list[TranscriptSegmentTiming],
    flag: CaptionReviewFlag,
) -> TranscriptSegmentTiming | None:
    if getattr(flag, "reason", None) == "probable truncation":
        stitched = _stitched_truncation_review_candidate(segments, flag)
        if stitched is not None:
            return stitched
    return _best_overlapping_segment(segments, flag)


def _stitched_truncation_review_candidate(
    segments: list[TranscriptSegmentTiming],
    flag: CaptionReviewFlag,
) -> TranscriptSegmentTiming | None:
    overlapping = [segment for segment in segments if _segment_overlap(segment.start, segment.end, flag.start, flag.end) > 0]
    if not overlapping:
        return None
    if len(overlapping) == 1:
        return overlapping[0]
    ordered = sorted(overlapping, key=lambda segment: (segment.start, segment.end))
    combined_text = _join_review_segment_texts(ordered)
    if not combined_text:
        return None
    probabilities = [segment.average_probability for segment in ordered if segment.average_probability is not None]
    average_probability = (sum(probabilities) / len(probabilities)) if probabilities else None
    return TranscriptSegmentTiming(
        text=combined_text,
        start=ordered[0].start,
        end=ordered[-1].end,
        average_probability=average_probability,
    )


def _should_accept_truncation_review_candidate(
    *,
    flag: CaptionReviewFlag,
    current_segment: TranscriptSegmentTiming,
    candidate_segment: TranscriptSegmentTiming,
) -> bool:
    if getattr(flag, "reason", None) != "probable truncation":
        return False
    candidate_probability = candidate_segment.average_probability
    if candidate_probability is None or candidate_probability < 0.75:
        return False
    flag_tokens = _normalized_word_tokens(flag.text)
    candidate_tokens = _normalized_word_tokens(candidate_segment.text)
    current_tokens = _normalized_word_tokens(current_segment.text)
    if not flag_tokens or len(candidate_tokens) <= len(current_tokens):
        return False
    prefix_overlap = _common_prefix_token_count(candidate_tokens, flag_tokens)
    minimum_prefix_overlap = max(4, len(flag_tokens) - 2)
    if prefix_overlap < minimum_prefix_overlap and not _contains_token_subsequence(candidate_tokens, flag_tokens):
        return False
    return True


def _join_review_segment_texts(segments: list[TranscriptSegmentTiming]) -> str:
    parts: list[str] = []
    for segment in segments:
        cleaned = _clean_caption_text(segment.text)
        if not cleaned:
            continue
        words = cleaned.split()
        if not words:
            continue
        if parts:
            previous_words = parts[-1].split()
            while previous_words and words and _normalize_token(previous_words[-1]) == _normalize_token(words[0]):
                words = words[1:]
            if not words:
                continue
        parts.append(" ".join(words))
    return _clean_caption_text(" ".join(parts))


def _normalized_word_tokens(text: str) -> list[str]:
    return [token for token in (_normalize_token(word) for word in _clean_caption_text(text).split()) if token]


def _common_prefix_token_count(left: list[str], right: list[str]) -> int:
    count = 0
    for left_token, right_token in zip(left, right):
        if left_token != right_token:
            break
        count += 1
    return count


def _contains_token_subsequence(haystack: list[str], needle: list[str]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    needle_length = len(needle)
    for index in range(len(haystack) - needle_length + 1):
        if haystack[index : index + needle_length] == needle:
            return True
    return False


def _segment_overlap(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    overlap = max(0.0, min(end_a, end_b) - max(start_a, start_b))
    if overlap <= 0.0:
        return 0.0
    span = max(0.05, max(end_a, end_b) - min(start_a, start_b))
    return overlap / span


def _format_caption_document(segments: list[TranscriptSegmentTiming], *, caption_format: CaptionFormat) -> str:
    rows = [(index, segment) for index, segment in enumerate(segments, start=1) if _clean_caption_text(segment.text)]
    if caption_format == CaptionFormat.VTT:
        blocks = ["WEBVTT", ""]
        for index, segment in rows:
            start_text = _format_caption_timestamp(segment.start, separator=".")
            end_text = _format_caption_timestamp(max(segment.end, segment.start + 0.2), separator=".")
            text = _wrap_caption_lines(_clean_caption_text(segment.text))
            blocks.extend([str(index), f"{start_text} --> {end_text}", text, ""])
        return "\n".join(blocks).rstrip() + "\n"

    blocks: list[str] = []
    for index, segment in rows:
        start_text = _format_caption_timestamp(segment.start, separator=",")
        end_text = _format_caption_timestamp(max(segment.end, segment.start + 0.2), separator=",")
        text = _wrap_caption_lines(_clean_caption_text(segment.text))
        blocks.extend([str(index), f"{start_text} --> {end_text}", text, ""])
    return "\n".join(blocks).rstrip() + ("\n" if blocks else "")


def _wrap_caption_lines(text: str) -> str:
    cleaned = _clean_caption_text(text)
    if len(cleaned) <= _CAPTION_MAX_LINE_CHARACTERS:
        return cleaned
    words = cleaned.split()
    best_break_index = None
    best_score = None
    for break_index in range(1, len(words)):
        first_line = " ".join(words[:break_index])
        second_line = " ".join(words[break_index:])
        longest_line = max(len(first_line), len(second_line))
        total_chars = len(first_line) + len(second_line)
        if total_chars > _CAPTION_MAX_CUE_CHARACTERS:
            continue
        imbalance = abs(len(first_line) - len(second_line))
        score = longest_line + (imbalance * 0.1)
        if best_score is None or score < best_score:
            best_break_index = break_index
            best_score = score
    if best_break_index is None:
        return cleaned
    return "\n".join(
        [
            " ".join(words[:best_break_index]).strip(),
            " ".join(words[best_break_index:]).strip(),
        ]
    ).strip()


def _clean_caption_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _format_caption_timestamp(seconds: float, *, separator: str) -> str:
    safe_seconds = max(0.0, float(seconds))
    total_milliseconds = int(round(safe_seconds * 1000.0))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{milliseconds:03d}"
