"""Speech-aware post-processing for long silences, filler words, and captions."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
import time
import wave
import math
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Callable

import numpy as np

from radcast.exceptions import EnhancementRuntimeError, JobCancelledError
from radcast.models import CaptionFormat, CaptionQualityMode, FillerRemovalMode, OutputFormat
from radcast.progress import estimate_caption_seconds, estimate_speech_cleanup_seconds
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
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_AGGRESSIVE_TRANSCRIBE_WINDOW_SECONDS = 8.0
_AGGRESSIVE_TRANSCRIBE_OVERLAP_SECONDS = 2.0
_CAPTION_FAST_WINDOW_SECONDS = 8.0
_CAPTION_FAST_OVERLAP_SECONDS = 1.5
_CAPTION_ACCURATE_WINDOW_SECONDS = 12.0
_CAPTION_ACCURATE_OVERLAP_SECONDS = 2.5
_CAPTION_REVIEWED_WINDOW_SECONDS = 24.0
_CAPTION_REVIEWED_OVERLAP_SECONDS = 2.5
_CAPTION_REVIEW_SWEEP_CONTEXT_SECONDS = 1.8
_CAPTION_REVIEW_MAX_FLAGS = 8
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
_NZ_LEGAL_CAPTION_PROMPT = (
    "This audio may include New Zealand legal and teaching terms. Prefer accurate forms such as Hansen, Tipping J, "
    "Moonen, NZBORA, New Zealand Bill of Rights Act, Parliament, presumption of innocence, freedom of expression, "
    "section 4, section 5, and section 6 when spoken clearly."
)
_CAPTION_MAX_LINES = 2
_CAPTION_MAX_LINE_CHARS = 45
_CAPTION_TARGET_LINE_CHARS = 42
_CAPTION_MAX_BLOCK_CHARS = _CAPTION_MAX_LINE_CHARS * _CAPTION_MAX_LINES
_BOUNDARY_DEDUPE_MAX_TOKENS = 3
_CAPTION_FRAGMENT_MAX_GAP_SECONDS = 0.45
_CAPTION_FRAGMENT_MIN_DURATION_SECONDS = 1.2
_CAPTION_FRAGMENT_MAX_COMBINED_DURATION_SECONDS = 12.5
_CAPTION_FRAGMENT_MAX_COMBINED_WORDS = 24
_CAPTION_STUB_MAX_DURATION_SECONDS = 1.25
_CAPTION_STUB_MAX_WORDS = 5
_SHORT_ORPHAN_TOKENS = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with"}
_LEADING_FRAGMENT_TOKENS = {
    "and",
    "as",
    "because",
    "but",
    "if",
    "in",
    "of",
    "or",
    "so",
    "that",
    "the",
    "then",
    "to",
    "when",
    "which",
    "with",
}
_TRAILING_FRAGMENT_TOKENS = {
    "a",
    "an",
    "and",
    "as",
    "because",
    "but",
    "for",
    "if",
    "in",
    "of",
    "or",
    "so",
    "that",
    "the",
    "then",
    "to",
    "when",
    "which",
    "with",
}

_LEAD_REPEAT_NORMALIZE_TOKENS = {
    "a",
    "an",
    "and",
    "but",
    "if",
    "or",
    "so",
    "that",
    "the",
}


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
class CaptionReviewFlag:
    start: float
    end: float
    text: str
    average_probability: float | None
    reason: str


@dataclass(frozen=True)
class CaptionQualityReport:
    average_probability: float | None
    low_confidence_segment_count: int
    total_segment_count: int
    flagged_segments: list[CaptionReviewFlag]
    review_recommended: bool

    def summary_text(self) -> str:
        if not self.total_segment_count:
            return "No caption segments were generated."
        if not self.review_recommended:
            return "Caption confidence looked stable."
        return (
            f"Caption review suggested: {self.low_confidence_segment_count} "
            f"low-confidence segment{'s' if self.low_confidence_segment_count != 1 else ''}."
        )


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


@dataclass(frozen=True)
class CaptionExportResult:
    caption_path: Path
    caption_format: CaptionFormat
    segment_count: int
    review_path: Path | None = None
    quality_report: CaptionQualityReport | None = None


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
class CaptionCue:
    text: str
    start: float
    end: float
    average_probability: float | None = None


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
        self.cleanup_model_size = os.environ.get("RADCAST_SPEECH_CLEANUP_MODEL", "small").strip() or "small"
        self.caption_fast_model_size = os.environ.get("RADCAST_CAPTION_FAST_MODEL", self.cleanup_model_size).strip() or self.cleanup_model_size
        self.caption_accurate_model_size = os.environ.get("RADCAST_CAPTION_ACCURATE_MODEL", "large-v3-turbo").strip() or "large-v3-turbo"
        self.caption_reviewed_model_size = os.environ.get("RADCAST_CAPTION_REVIEWED_MODEL", "large-v3").strip() or "large-v3"
        self.device = os.environ.get("RADCAST_SPEECH_CLEANUP_DEVICE", "auto").strip() or "auto"
        self.compute_type = os.environ.get("RADCAST_SPEECH_CLEANUP_COMPUTE_TYPE", "int8").strip() or "int8"
        self.transcribe_language = os.environ.get("RADCAST_SPEECH_CLEANUP_LANGUAGE", "en").strip().lower() or "en"
        self.beam_size = max(1, int(os.environ.get("RADCAST_SPEECH_CLEANUP_BEAM_SIZE", "3")))
        self.caption_fast_beam_size = max(1, int(os.environ.get("RADCAST_CAPTION_FAST_BEAM_SIZE", str(self.beam_size))))
        self.caption_accurate_beam_size = max(1, int(os.environ.get("RADCAST_CAPTION_ACCURATE_BEAM_SIZE", "5")))
        self.caption_reviewed_beam_size = max(1, int(os.environ.get("RADCAST_CAPTION_REVIEWED_BEAM_SIZE", "7")))
        self._models: dict[str, object] = {}
        self._model_lock = threading.Lock()

    def estimate_caption_runtime_seconds(
        self,
        duration_seconds: float,
        *,
        quality_mode: CaptionQualityMode = CaptionQualityMode.REVIEWED,
    ) -> int:
        normalized_quality = _normalize_caption_quality_mode(quality_mode)
        base_seconds = estimate_caption_seconds(duration_seconds, quality_mode=normalized_quality)
        profile = self._caption_profile_for_mode(
            normalized_quality,
            caption_prompt=None,
            duration_seconds=duration_seconds,
        )
        if normalized_quality == CaptionQualityMode.REVIEWED:
            first_pass_ready = self._model_cache_ready(profile.model_size)
            review_ready = self._model_cache_ready(self.caption_reviewed_model_size)
            if first_pass_ready and review_ready:
                return base_seconds
            cold_start_seconds = 0
            if not first_pass_ready:
                cold_start_seconds += 65
            if not review_ready:
                cold_start_seconds += 80
            return min(base_seconds + cold_start_seconds, 24 * 60)
        if self._model_cache_ready(profile.model_size):
            return base_seconds
        if normalized_quality == CaptionQualityMode.FAST:
            cold_start_seconds = 18
        elif normalized_quality == CaptionQualityMode.ACCURATE:
            cold_start_seconds = 65
        else:
            cold_start_seconds = 145
        return min(base_seconds + cold_start_seconds, 22 * 60)

    @staticmethod
    def cleanup_requested(max_silence_seconds: float | None, remove_filler_words: bool) -> bool:
        return max_silence_seconds is not None or bool(remove_filler_words)

    def capability_status(self) -> tuple[bool, str]:
        if find_spec("faster_whisper") is None:
            return False, "Install faster-whisper to enable long-silence trimming, filler-word cleanup, and caption export."
        return True, (
            "Speech cleanup and caption export are available with faster-whisper "
            f"(cleanup: {self.cleanup_model_size}, captions: {self.caption_accurate_model_size}, review: {self.caption_reviewed_model_size})."
        )

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

    def _model_cache_ready(self, model_size: str | None) -> bool:
        resolved_model_size = str(model_size or "").strip()
        if not resolved_model_size:
            return False
        if resolved_model_size in self._models:
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
        caption_prompt = _build_caption_prompt(caption_glossary)
        profile = self._caption_profile_for_mode(
            quality_mode,
            caption_prompt=caption_prompt,
            duration_seconds=input_duration,
        )
        caption_eta_seconds = self.estimate_caption_runtime_seconds(input_duration, quality_mode=quality_mode)
        review_budget = _caption_review_flag_budget(input_duration)
        started_at = time.monotonic()
        if on_stage:
            caption_window_count = _window_count_for_duration(
                input_duration,
                profile.window_seconds,
                profile.overlap_seconds,
            )
            detail = (
                f"Loading {profile.model_size} caption model and transcribing speech for captions."
                if not self._model_cache_ready(profile.model_size)
                else "Transcribing speech for captions."
            )
            detail = _windowed_stage_detail(detail, 1, caption_window_count)
            on_stage(0.02, detail, caption_eta_seconds)

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
                transcribe_detail="Transcribing speech for captions.",
                cancel_check=cancel_check,
                force_windowed=True,
                preserve_fillers=False,
                model_size=profile.model_size,
                beam_size=profile.beam_size,
                condition_on_previous_text=profile.condition_on_previous_text,
                initial_prompt=profile.initial_prompt,
                window_seconds=profile.window_seconds,
                overlap_seconds=profile.overlap_seconds,
                language_override="auto",
            )
            segments = _dedupe_caption_segments(segments)

            if cancel_check and cancel_check():
                raise JobCancelledError("job cancelled")

            quality_report = _build_caption_quality_report(segments)
            if profile.review_sweep and quality_report.flagged_segments:
                if on_stage:
                    on_stage(
                        0.82,
                        _caption_review_detail(0, min(review_budget, len(quality_report.flagged_segments))),
                        _remaining_cleanup_eta(started_at, caption_eta_seconds, floor_seconds=10),
                    )
                segments = self._review_and_correct_caption_segments(
                    analysis_wav=analysis_wav,
                    base_segments=segments,
                    quality_report=quality_report,
                    prompt_text=caption_prompt,
                    on_stage=on_stage,
                    started_at=started_at,
                    caption_eta_seconds=caption_eta_seconds,
                    review_budget=review_budget,
                    cancel_check=cancel_check,
                )
                segments = _dedupe_caption_segments(segments)
                quality_report = _build_caption_quality_report(segments)

            segments = _compose_accessible_caption_blocks(segments)
            quality_report = _build_caption_quality_report(segments)

            output_path = audio_path.with_suffix(f".{caption_format.value}")
            review_path = None
            if on_stage:
                on_stage(
                    0.92,
                    f"Writing {caption_format.value.upper()} captions.",
                    _remaining_cleanup_eta(started_at, caption_eta_seconds, floor_seconds=2),
                )
            output_path.write_text(
                _render_caption_document(segments, caption_format=caption_format),
                encoding="utf-8",
            )
            if quality_report.review_recommended:
                review_path = output_path.parent / f"{output_path.name}.review.txt"
                review_path.write_text(_format_caption_review_document(quality_report), encoding="utf-8")
        return CaptionExportResult(
            caption_path=output_path,
            caption_format=caption_format,
            segment_count=len([segment for segment in segments if _clean_caption_text(segment.text)]),
            review_path=review_path,
            quality_report=quality_report,
        )

    def _load_model(self, model_size: str | None = None):
        resolved_model_size = str(model_size or self.cleanup_model_size).strip() or self.cleanup_model_size
        cached = self._models.get(resolved_model_size)
        if cached is not None:
            return cached
        with self._model_lock:
            cached = self._models.get(resolved_model_size)
            if cached is not None:
                return cached
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:  # pragma: no cover - availability is checked before runtime use
                raise EnhancementRuntimeError(
                    "faster-whisper is required for speech cleanup. Install with 'pip install -e .'."
                ) from exc
            model = WhisperModel(resolved_model_size, device=self.device, compute_type=self.compute_type)
            self._models[resolved_model_size] = model
            return model

    def _transcribe_file(
        self,
        model,
        audio_path: Path,
        *,
        preserve_fillers: bool,
        beam_size: int | None = None,
        condition_on_previous_text: bool = False,
        initial_prompt: str | None = None,
        language_override: str | None = None,
    ):
        kwargs = {
            "beam_size": max(1, int(beam_size or self.beam_size)),
            "word_timestamps": True,
            "vad_filter": not preserve_fillers,
            "condition_on_previous_text": condition_on_previous_text,
        }
        prompt_text = initial_prompt
        if preserve_fillers and not prompt_text:
            prompt_text = _AGGRESSIVE_FILLER_PROMPT
        if prompt_text:
            kwargs["initial_prompt"] = prompt_text
        language = self.transcribe_language if language_override is None else language_override
        if language and language != "auto":
            kwargs["language"] = language
        segment_iter, _info = model.transcribe(str(audio_path), **kwargs)
        return segment_iter

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
        model_size: str | None = None,
        beam_size: int | None = None,
        condition_on_previous_text: bool = False,
        initial_prompt: str | None = None,
        window_seconds: float | None = None,
        overlap_seconds: float | None = None,
        language_override: str | None = None,
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
                model_size=model_size,
                beam_size=effective_beam_size,
                condition_on_previous_text=condition_on_previous_text,
                initial_prompt=initial_prompt,
                window_seconds=window_seconds,
                overlap_seconds=overlap_seconds,
                language_override=language_override,
            )

        if cancel_check and cancel_check():
            raise JobCancelledError("job cancelled")
        model = self._load_model(model_size)

        words: list[TranscriptWordTiming] = []
        segments: list[TranscriptSegmentTiming] = []
        last_progress_emit_at = 0.0
        transcribe_kwargs = {
            "preserve_fillers": preserve_fillers,
            "beam_size": effective_beam_size,
            "condition_on_previous_text": condition_on_previous_text,
            "initial_prompt": initial_prompt,
        }
        if language_override is not None:
            transcribe_kwargs["language_override"] = language_override
        for seg in self._transcribe_file(
            model,
            audio_path,
            **transcribe_kwargs,
        ):
            if cancel_check and cancel_check():
                raise JobCancelledError("job cancelled")
            start = max(0.0, float(seg.start))
            end = max(start, float(seg.end))
            text = str(seg.text or "").strip()
            probabilities: list[float] = []
            for word in seg.words or []:
                if word.probability is not None:
                    probabilities.append(float(word.probability))
            segments.append(
                TranscriptSegmentTiming(
                    text=text,
                    start=start,
                    end=end,
                    average_probability=(sum(probabilities) / len(probabilities)) if probabilities else None,
                )
            )
            for word in seg.words or []:
                word_start = max(0.0, float(word.start))
                word_end = max(word_start, float(word.end))
                words.append(
                    TranscriptWordTiming(
                        text=str(word.word or "").strip(),
                        start=word_start,
                        end=word_end,
                        probability=float(word.probability) if word.probability is not None else None,
                    )
                )
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
        model_size: str | None = None,
        beam_size: int | None = None,
        condition_on_previous_text: bool = False,
        initial_prompt: str | None = None,
        window_seconds: float | None = None,
        overlap_seconds: float | None = None,
        language_override: str | None = None,
    ) -> tuple[list[TranscriptWordTiming], list[TranscriptSegmentTiming]]:
        if cancel_check and cancel_check():
            raise JobCancelledError("job cancelled")
        model = self._load_model(model_size)
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
                if language_override is not None:
                    transcribe_kwargs["language_override"] = language_override
                transcribed_segments = self._transcribe_file(
                    model,
                    window_path,
                    **transcribe_kwargs,
                )

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
                        _windowed_stage_detail(transcribe_detail, processed_windows, total_windows),
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
        duration_seconds: float,
    ) -> CaptionTranscriptionProfile:
        if caption_quality_mode == CaptionQualityMode.FAST:
            return CaptionTranscriptionProfile(
                model_size=self.caption_fast_model_size,
                beam_size=self.caption_fast_beam_size,
                window_seconds=_CAPTION_FAST_WINDOW_SECONDS,
                overlap_seconds=_CAPTION_FAST_OVERLAP_SECONDS,
                condition_on_previous_text=False,
                initial_prompt=caption_prompt,
            )
        if caption_quality_mode == CaptionQualityMode.REVIEWED:
            reviewed_window_seconds = _reviewed_caption_window_seconds(duration_seconds)
            reviewed_overlap_seconds = _reviewed_caption_overlap_seconds(reviewed_window_seconds)
            return CaptionTranscriptionProfile(
                model_size=self.caption_accurate_model_size,
                beam_size=self.caption_accurate_beam_size,
                window_seconds=reviewed_window_seconds,
                overlap_seconds=reviewed_overlap_seconds,
                condition_on_previous_text=True,
                initial_prompt=caption_prompt,
                review_sweep=True,
            )
        return CaptionTranscriptionProfile(
            model_size=self.caption_accurate_model_size,
            beam_size=self.caption_accurate_beam_size,
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
        review_budget: int | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> list[TranscriptSegmentTiming]:
        if not quality_report.flagged_segments:
            return base_segments
        model = self._load_model(self.caption_reviewed_model_size)
        waveform, sample_rate = _read_pcm16_wav(analysis_wav)
        corrected = list(base_segments)
        review_targets = quality_report.flagged_segments[: max(1, int(review_budget or _CAPTION_REVIEW_MAX_FLAGS))]
        with tempfile.TemporaryDirectory(prefix="radcast_caption_review_") as tmp:
            tmp_path = Path(tmp)
            for index, flag in enumerate(review_targets, start=1):
                if cancel_check and cancel_check():
                    raise JobCancelledError("job cancelled")
                if on_stage and started_at is not None and caption_eta_seconds is not None:
                    on_stage(
                        0.82 + (0.08 * ((index - 1) / max(1, len(review_targets)))),
                        _caption_review_detail(index, len(review_targets)),
                        _caption_review_eta_seconds(
                            started_at=started_at,
                            caption_eta_seconds=caption_eta_seconds,
                            review_index=index,
                            review_total=len(review_targets),
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
                )
                if candidate_segment is None:
                    continue
                current_segment = corrected[matched_index]
                current_probability = current_segment.average_probability if current_segment.average_probability is not None else -1.0
                next_probability = candidate_segment.average_probability if candidate_segment.average_probability is not None else current_probability
                if next_probability + 0.03 < current_probability:
                    continue
                corrected[matched_index] = candidate_segment
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
        review_segments = self._transcribe_file(
            model,
            snippet_path,
            preserve_fillers=False,
            beam_size=self.caption_reviewed_beam_size + 1,
            condition_on_previous_text=True,
            initial_prompt=_combine_prompt_parts(prompt_text, _CAPTION_REVIEW_PROMPT),
        )
        _, candidate_segments = _collect_timing_rows(
            list(review_segments),
            window_offset_seconds=snippet_start,
            keep_start_seconds=0.0,
            keep_end_seconds=max(0.0, snippet_end - snippet_start),
        )
        best = _best_overlapping_segment(candidate_segments, flag)
        if best is None:
            return None
        if not _clean_caption_text(best.text):
            return None
        if _clean_caption_text(best.text) == _clean_caption_text(flag.text) and (
            best.average_probability is None
            or (flag.average_probability is not None and best.average_probability <= flag.average_probability + 0.01)
        ):
            return None
        return TranscriptSegmentTiming(
            text=best.text,
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
    prompt_parts = [_NZ_ENGLISH_STYLE_PROMPT, _MAORI_GLOSSARY_PROMPT, _NZ_LEGAL_CAPTION_PROMPT]
    if glossary_terms:
        prompt_parts.append(
            "Also prefer these course or project terms if spoken clearly: " + ", ".join(glossary_terms) + "."
        )
    return _combine_prompt_parts(*prompt_parts) or _NZ_ENGLISH_STYLE_PROMPT


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
) -> int:
    safe_processed_windows = max(1, int(processed_windows))
    safe_total_windows = max(safe_processed_windows, int(total_windows))
    remaining_windows = max(0, safe_total_windows - safe_processed_windows)
    average_window_seconds = max(1.0, float(elapsed_seconds) / safe_processed_windows)
    window_projection = remaining_windows * average_window_seconds
    coverage_projection = _transcription_eta_seconds(
        elapsed_seconds=elapsed_seconds,
        cleanup_eta_seconds=cleanup_eta_seconds,
        coverage=coverage,
    )
    baseline_projection = max(
        1.0,
        (max(1.0, float(cleanup_eta_seconds)) / safe_total_windows) * remaining_windows,
    )
    capped_window_projection = min(
        window_projection,
        max(baseline_projection * 1.65, coverage_projection * 1.2),
    )
    remaining = max(baseline_projection, capped_window_projection, coverage_projection * 0.92)
    remaining = min(
        remaining,
        max(
            float(cleanup_eta_seconds) * 1.45,
            baseline_projection * 1.65,
        ),
    )
    progress_ratio = safe_processed_windows / safe_total_windows
    if progress_ratio < 0.3:
        remaining *= 1.14
    elif progress_ratio < 0.55:
        remaining *= 1.08
    elif progress_ratio < 0.8:
        remaining *= 1.04
    remaining += 4.0
    if remaining_windows >= 6:
        floor_seconds = 24
    elif remaining_windows >= 3:
        floor_seconds = 14
    elif remaining_windows >= 1:
        floor_seconds = 8
    else:
        floor_seconds = 3
    return max(floor_seconds, int(round(max(1.0, remaining))))


def _windowed_stage_detail(base_detail: str, processed_windows: int, total_windows: int) -> str:
    clean_detail = str(base_detail or "").strip() or "Processing speech."
    if total_windows <= 1:
        return clean_detail
    return f"{clean_detail} Window {processed_windows} of {total_windows}."


def _window_count_for_duration(
    duration_seconds: float,
    window_seconds: float,
    overlap_seconds: float,
) -> int:
    safe_duration = max(0.0, float(duration_seconds))
    resolved_window_seconds = min(max(float(window_seconds), 1.0), max(safe_duration, 1.0))
    resolved_overlap_seconds = min(float(overlap_seconds), max(0.0, resolved_window_seconds / 2.0))
    step_seconds = max(0.5, resolved_window_seconds - resolved_overlap_seconds)
    return max(1, int(math.ceil(max(safe_duration - resolved_window_seconds, 0.0) / step_seconds)) + 1)


def _caption_review_flag_budget(duration_seconds: float | None) -> int:
    safe_duration = max(1.0, float(duration_seconds or 1.0))
    if safe_duration >= 12 * 60:
        return 3
    if safe_duration >= 6 * 60:
        return 4
    if safe_duration >= 3 * 60:
        return 6
    return _CAPTION_REVIEW_MAX_FLAGS


def _reviewed_caption_window_seconds(duration_seconds: float | None) -> float:
    safe_duration = max(1.0, float(duration_seconds or 1.0))
    if safe_duration >= 6 * 60:
        return 30.0
    if safe_duration >= 3 * 60:
        return 28.0
    return _CAPTION_REVIEWED_WINDOW_SECONDS


def _reviewed_caption_overlap_seconds(window_seconds: float) -> float:
    if window_seconds >= 30.0:
        return 2.0
    if window_seconds >= 28.0:
        return 2.25
    return _CAPTION_REVIEWED_OVERLAP_SECONDS


def _caption_review_detail(review_index: int, review_total: int) -> str:
    safe_total = max(0, int(review_total))
    if safe_total <= 0:
        return "Reviewing low-confidence caption lines."
    if review_index <= 0:
        return f"Preparing caption review sweep ({safe_total} flagged segment{'s' if safe_total != 1 else ''})."
    return f"Reviewing difficult caption segments ({review_index} of {safe_total})."


def _caption_review_eta_seconds(
    *,
    started_at: float,
    caption_eta_seconds: int,
    review_index: int,
    review_total: int,
) -> int:
    remaining = _remaining_cleanup_eta(started_at, caption_eta_seconds, floor_seconds=8)
    safe_total = max(1, int(review_total))
    safe_index = max(0, min(safe_total, int(review_index)))
    remaining_reviews = max(0, safe_total - safe_index)
    return max(8, min(remaining, 18 + (remaining_reviews * 9)))


def _collect_timing_rows(
    transcribed_segments: list[object],
    *,
    window_offset_seconds: float,
    keep_start_seconds: float,
    keep_end_seconds: float,
) -> tuple[list[TranscriptWordTiming], list[TranscriptSegmentTiming]]:
    words: list[TranscriptWordTiming] = []
    segments: list[TranscriptSegmentTiming] = []
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


def _build_caption_quality_report(segments: list[TranscriptSegmentTiming]) -> CaptionQualityReport:
    clean_segments = [segment for segment in segments if _clean_caption_text(segment.text)]
    probabilities = [segment.average_probability for segment in clean_segments if segment.average_probability is not None]
    average_probability = (sum(probabilities) / len(probabilities)) if probabilities else None
    flagged_segments: list[CaptionReviewFlag] = []
    for segment in clean_segments:
        text = _clean_caption_text(segment.text)
        reason = _caption_review_reason(segment, average_probability=average_probability)
        if not reason:
            continue
        flagged_segments.append(
            CaptionReviewFlag(
                start=segment.start,
                end=segment.end,
                text=text,
                average_probability=segment.average_probability,
                reason=reason,
            )
        )
    low_confidence_segment_count = len(flagged_segments)
    review_recommended = low_confidence_segment_count > 0 or (
        average_probability is not None and average_probability < 0.72 and len(clean_segments) >= 4
    )
    return CaptionQualityReport(
        average_probability=average_probability,
        low_confidence_segment_count=low_confidence_segment_count,
        total_segment_count=len(clean_segments),
        flagged_segments=flagged_segments[:24],
        review_recommended=review_recommended,
    )


def _caption_review_reason(
    segment: TranscriptSegmentTiming,
    *,
    average_probability: float | None,
) -> str | None:
    text = _clean_caption_text(segment.text)
    if not text:
        return None
    probability = segment.average_probability
    if probability is None:
        return "No word confidence data was available for this caption line."
    low_threshold = 0.4
    warn_threshold = 0.54
    if average_probability is not None:
        low_threshold = min(low_threshold, max(0.32, average_probability - 0.24))
        warn_threshold = min(warn_threshold, max(0.44, average_probability - 0.16))
    token_count = len(text.split())
    if probability < low_threshold:
        return "Very low confidence caption line."
    if probability < warn_threshold and token_count >= 7:
        return "Low confidence on a longer caption line."
    return None


def _format_caption_review_document(report: CaptionQualityReport) -> str:
    lines = ["RADcast Caption Review", ""]
    if report.average_probability is not None:
        lines.append(f"Average word confidence: {report.average_probability:.0%}")
    lines.append(f"Low-confidence caption lines: {report.low_confidence_segment_count}")
    lines.append(f"Total caption lines: {report.total_segment_count}")
    lines.append("")
    if not report.flagged_segments:
        lines.append("No specific caption lines were flagged.")
        return "\n".join(lines).rstrip() + "\n"
    lines.append("Review these timestamp ranges:")
    lines.append("")
    for flag in report.flagged_segments:
        start_text = _format_caption_timestamp(flag.start, separator=".")
        end_text = _format_caption_timestamp(max(flag.end, flag.start + 0.2), separator=".")
        confidence_text = (
            f"{flag.average_probability:.0%}" if flag.average_probability is not None else "unknown"
        )
        lines.append(f"{start_text} --> {end_text} | confidence {confidence_text}")
        lines.append(f"Reason: {flag.reason}")
        lines.append(flag.text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


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


def _compose_accessible_caption_blocks(
    segments: list[TranscriptSegmentTiming],
) -> list[TranscriptSegmentTiming]:
    composed: list[TranscriptSegmentTiming] = []
    for segment in segments:
        cleaned_text = _clean_caption_text(segment.text)
        if not cleaned_text:
            continue
        sentence_units = _split_segment_into_sentence_units(segment)
        for unit_text, unit_start, unit_end, unit_probability in sentence_units:
            for cue in _split_sentence_unit_into_cues(
                unit_text,
                start=unit_start,
                end=unit_end,
                average_probability=unit_probability,
            ):
                composed.append(cue)
    return _refine_accessible_caption_blocks(_dedupe_adjacent_caption_blocks(composed))


def _split_segment_into_sentence_units(
    segment: TranscriptSegmentTiming,
) -> list[tuple[str, float, float, float | None]]:
    cleaned_text = _clean_caption_text(segment.text)
    if not cleaned_text:
        return []
    pieces = [piece.strip() for piece in _SENTENCE_SPLIT_RE.split(cleaned_text) if piece.strip()]
    if len(pieces) <= 1:
        return [(cleaned_text, segment.start, segment.end, segment.average_probability)]

    total_chars = max(1, sum(len(piece) for piece in pieces))
    duration = max(0.2, segment.end - segment.start)
    cursor = segment.start
    units: list[tuple[str, float, float, float | None]] = []
    for index, piece in enumerate(pieces):
        remaining_chars = sum(len(item) for item in pieces[index:])
        if index == len(pieces) - 1 or remaining_chars <= 0:
            piece_end = segment.end
        else:
            piece_duration = duration * (len(piece) / total_chars)
            piece_end = min(segment.end, max(cursor + 0.2, cursor + piece_duration))
        units.append((piece, cursor, piece_end, segment.average_probability))
        cursor = piece_end
    if units:
        last_text, last_start, _last_end, last_probability = units[-1]
        units[-1] = (last_text, last_start, segment.end, last_probability)
    return units


def _split_sentence_unit_into_cues(
    text: str,
    *,
    start: float,
    end: float,
    average_probability: float | None,
) -> list[TranscriptSegmentTiming]:
    words = text.split()
    if not words:
        return []
    if len(_clean_caption_text(text)) <= _CAPTION_MAX_BLOCK_CHARS:
        return [
            TranscriptSegmentTiming(
                text=_wrap_caption_block_lines(text),
                start=start,
                end=end,
                average_probability=average_probability,
            )
        ]

    cues: list[TranscriptSegmentTiming] = []
    total_words = len(words)
    cursor = 0
    duration = max(0.2, end - start)
    while cursor < total_words:
        remaining_words = total_words - cursor
        chunk_size = _choose_caption_chunk_size(words, cursor)
        chunk_words = words[cursor : cursor + chunk_size]
        chunk_text = " ".join(chunk_words)
        chunk_start = start + (duration * (cursor / total_words))
        chunk_end = end if cursor + chunk_size >= total_words else start + (duration * ((cursor + chunk_size) / total_words))
        chunk_end = max(chunk_start + 0.2, chunk_end)
        cues.append(
            TranscriptSegmentTiming(
                text=_wrap_caption_block_lines(chunk_text),
                start=chunk_start,
                end=chunk_end,
                average_probability=average_probability,
            )
        )
        cursor += chunk_size
        if remaining_words == chunk_size:
            break
    if cues:
        last = cues[-1]
        cues[-1] = TranscriptSegmentTiming(
            text=last.text,
            start=last.start,
            end=end,
            average_probability=last.average_probability,
        )
    return cues


def _choose_caption_chunk_size(words: list[str], start_index: int) -> int:
    best_index = start_index + 1
    best_score = float("-inf")
    char_count = 0
    for index in range(start_index, len(words)):
        word = words[index]
        char_count += len(word) + (1 if index > start_index else 0)
        chunk_size = index - start_index + 1
        if char_count > _CAPTION_MAX_BLOCK_CHARS and chunk_size > 1:
            break
        score = 0.0
        if char_count <= _CAPTION_MAX_BLOCK_CHARS:
            score += 10.0
        score -= abs(char_count - (_CAPTION_TARGET_LINE_CHARS * _CAPTION_MAX_LINES * 0.8)) / 12.0
        if index < len(words) - 1 and not word.endswith((".", "!", "?", ",", ";", ":")):
            if char_count < _CAPTION_TARGET_LINE_CHARS:
                score -= 6.0 + ((_CAPTION_TARGET_LINE_CHARS - char_count) / 2.0)
        if word.endswith((".", "!", "?")):
            score += 7.0
        elif word.endswith((",", ";", ":")):
            score += 4.0
        elif len(word) <= 3 and word.lower() in _SHORT_ORPHAN_TOKENS:
            score -= 3.0
        wrapped_preview = _wrap_caption_block_lines(" ".join(words[start_index : index + 1]))
        score += _caption_fragment_layout_score(wrapped_preview.splitlines())
        current_word = _normalize_token(word)
        if current_word in _TRAILING_FRAGMENT_TOKENS and index < len(words) - 1:
            score -= 10.0
        if index + 1 < len(words):
            next_word = _normalize_token(words[index + 1])
            if next_word in _LEADING_FRAGMENT_TOKENS:
                score -= 8.0
        if score > best_score:
            best_score = score
            best_index = index + 1
    return max(1, best_index - start_index)


def _wrap_caption_block_lines(text: str) -> str:
    cleaned = _clean_caption_text(text)
    if len(cleaned) <= _CAPTION_MAX_LINE_CHARS:
        return cleaned
    words = cleaned.split()
    if len(words) <= 1:
        return cleaned

    best_break = None
    best_score = float("-inf")
    for index in range(1, len(words)):
        left = " ".join(words[:index])
        right = " ".join(words[index:])
        if len(left) > _CAPTION_MAX_LINE_CHARS or len(right) > _CAPTION_MAX_LINE_CHARS:
            continue
        score = 0.0
        score -= abs(len(left) - len(right)) / 5.0
        if words[index - 1].endswith((".", "!", "?")):
            score += 5.0
        elif words[index - 1].endswith((",", ";", ":")):
            score += 3.0
        left_last_word = _normalize_token(words[index - 1])
        right_first_word = _normalize_token(words[index])
        if left_last_word in _TRAILING_FRAGMENT_TOKENS:
            score -= 8.0
        if right_first_word in _LEADING_FRAGMENT_TOKENS and len(right.split()) <= 3:
            score -= 3.0
        if len(right.split()) == 1:
            score -= 6.0
        if words[index].lower() in _SHORT_ORPHAN_TOKENS:
            score -= 2.0
        if score > best_score:
            best_score = score
            best_break = index

    if best_break is None:
        midpoint = max(1, len(words) // 2)
        left = " ".join(words[:midpoint])
        right = " ".join(words[midpoint:])
        return f"{left}\n{right}"

    left = " ".join(words[:best_break])
    right = " ".join(words[best_break:])
    return f"{left}\n{right}"


def _caption_fragment_layout_score(lines: list[str]) -> float:
    score = 0.0
    for line_index, line in enumerate(lines):
        words = line.split()
        if not words:
            continue
        last_word = _normalize_token(words[-1])
        first_word = _normalize_token(words[0])
        if last_word in _TRAILING_FRAGMENT_TOKENS:
            score -= 8.0
        if line_index > 0 and first_word in _LEADING_FRAGMENT_TOKENS and len(words) <= 3:
            score -= 3.0
    return score


def _dedupe_adjacent_caption_blocks(
    segments: list[TranscriptSegmentTiming],
) -> list[TranscriptSegmentTiming]:
    if not segments:
        return []
    deduped: list[TranscriptSegmentTiming] = []
    for segment in sorted(segments, key=lambda item: (item.start, item.end)):
        normalized_text = _clean_caption_text(segment.text)
        display_text = str(segment.text or "").strip()
        normalized_segment = TranscriptSegmentTiming(
            text=display_text,
            start=segment.start,
            end=segment.end,
            average_probability=segment.average_probability,
        )
        if not deduped:
            deduped.append(normalized_segment)
            continue
        previous = deduped[-1]
        overlap = _boundary_overlap_tokens(previous.text, normalized_text)
        if overlap > 0:
            next_words = normalized_text.split()[overlap:]
            if next_words:
                normalized_segment = TranscriptSegmentTiming(
                    text=" ".join(next_words),
                    start=normalized_segment.start,
                    end=normalized_segment.end,
                    average_probability=normalized_segment.average_probability,
                )
        if normalized_segment.text:
            deduped.append(normalized_segment)
    return deduped


def _refine_accessible_caption_blocks(
    segments: list[TranscriptSegmentTiming],
) -> list[TranscriptSegmentTiming]:
    merged = _merge_caption_fragments(segments)
    refined: list[TranscriptSegmentTiming] = []
    for segment in merged:
        text = _clean_caption_text(segment.text)
        if not text:
            continue
        if len(text) <= _CAPTION_MAX_BLOCK_CHARS:
            refined.append(
                TranscriptSegmentTiming(
                    text=_wrap_caption_block_lines(text),
                    start=segment.start,
                    end=segment.end,
                    average_probability=segment.average_probability,
                )
            )
            continue
        refined.extend(
            _split_sentence_unit_into_cues(
                text,
                start=segment.start,
                end=segment.end,
                average_probability=segment.average_probability,
            )
        )
    rebalanced = _rebalance_adjacent_caption_blocks(refined)
    repaired = _merge_short_caption_stubs(rebalanced)
    finalized: list[TranscriptSegmentTiming] = []
    for segment in _dedupe_adjacent_caption_blocks(repaired):
        finalized.extend(_split_or_wrap_caption_segment(segment))
    return finalized


def _rebalance_adjacent_caption_blocks(
    segments: list[TranscriptSegmentTiming],
) -> list[TranscriptSegmentTiming]:
    if len(segments) < 2:
        return segments
    rebalanced = list(segments)
    for index in range(len(rebalanced) - 1):
        current = rebalanced[index]
        following = rebalanced[index + 1]
        if not _should_rebalance_caption_pair(current, following):
            continue
        replacement = _best_rebalanced_caption_pair(current, following)
        if replacement is None:
            continue
        rebalanced[index], rebalanced[index + 1] = replacement
    return rebalanced


def _merge_short_caption_stubs(
    segments: list[TranscriptSegmentTiming],
) -> list[TranscriptSegmentTiming]:
    if len(segments) < 2:
        return segments
    merged = list(segments)
    index = 0
    while index < len(merged):
        current = merged[index]
        if not _is_short_caption_stub(current):
            index += 1
            continue
        if index + 1 < len(merged) and _should_attach_stub_to_next(current):
            combined = _merge_caption_pair(current, merged[index + 1])
            replacement = _split_or_wrap_caption_segment(combined)
            merged[index : index + 2] = replacement
            index = max(0, index - 1)
            continue
        if index > 0:
            combined = _merge_caption_pair(merged[index - 1], current)
            replacement = _split_or_wrap_caption_segment(combined)
            merged[index - 1 : index + 1] = replacement
            index = max(0, index - 2)
            continue
        if index + 1 < len(merged):
            combined = _merge_caption_pair(current, merged[index + 1])
            replacement = _split_or_wrap_caption_segment(combined)
            merged[index : index + 2] = replacement
            continue
        index += 1
    return _rebalance_adjacent_caption_blocks(merged)


def _merge_caption_fragments(
    segments: list[TranscriptSegmentTiming],
) -> list[TranscriptSegmentTiming]:
    ordered = [
        TranscriptSegmentTiming(
            text=_clean_caption_text(segment.text),
            start=segment.start,
            end=segment.end,
            average_probability=segment.average_probability,
        )
        for segment in sorted(segments, key=lambda item: (item.start, item.end))
        if _clean_caption_text(segment.text)
    ]
    if not ordered:
        return []

    merged: list[TranscriptSegmentTiming] = []
    index = 0
    while index < len(ordered):
        current = ordered[index]
        if index + 1 < len(ordered) and _should_attach_fragment_to_next(current, ordered[index + 1]):
            merged.append(_merge_caption_pair(current, ordered[index + 1]))
            index += 2
            continue
        if merged and _should_attach_fragment_to_previous(merged[-1], current):
            merged[-1] = _merge_caption_pair(merged[-1], current)
            index += 1
            continue
        merged.append(current)
        index += 1
    return merged


def _should_attach_fragment_to_next(
    current: TranscriptSegmentTiming,
    following: TranscriptSegmentTiming,
) -> bool:
    text = _clean_caption_text(current.text)
    if not text:
        return False
    words = text.split()
    if not words:
        return False
    duration = max(0.0, current.end - current.start)
    last_word = _normalize_token(words[-1])
    following_text = _clean_caption_text(following.text)
    looks_incomplete = (
        last_word in _TRAILING_FRAGMENT_TOKENS
        or text.endswith(("…", "..."))
        or (duration < _CAPTION_FRAGMENT_MIN_DURATION_SECONDS and last_word in _TRAILING_FRAGMENT_TOKENS)
        or (
            duration < 2.5
            and len(words) <= 4
            and not text.endswith((".", "!", "?", ",", ";", ":"))
            and following_text[:1].islower()
        )
    )
    return looks_incomplete and _can_merge_caption_pair(current, following)


def _should_attach_fragment_to_previous(
    previous: TranscriptSegmentTiming,
    current: TranscriptSegmentTiming,
) -> bool:
    previous_text = _clean_caption_text(previous.text)
    if previous_text.endswith((".", "!", "?")):
        return False
    text = _clean_caption_text(current.text)
    if not text:
        return False
    words = text.split()
    if not words:
        return False
    duration = max(0.0, current.end - current.start)
    first_word = _normalize_token(words[0])
    looks_leading = (
        first_word in _LEADING_FRAGMENT_TOKENS
        or text[:1].islower()
        or (duration < _CAPTION_FRAGMENT_MIN_DURATION_SECONDS and first_word in _LEADING_FRAGMENT_TOKENS)
    )
    return looks_leading and _can_merge_caption_pair(previous, current)


def _can_merge_caption_pair(
    left: TranscriptSegmentTiming,
    right: TranscriptSegmentTiming,
) -> bool:
    if right.start - left.end > _CAPTION_FRAGMENT_MAX_GAP_SECONDS:
        return False
    combined_duration = max(0.0, right.end - left.start)
    if combined_duration > _CAPTION_FRAGMENT_MAX_COMBINED_DURATION_SECONDS:
        return False
    combined_words = len(_clean_caption_text(left.text).split()) + len(_clean_caption_text(right.text).split())
    return combined_words <= _CAPTION_FRAGMENT_MAX_COMBINED_WORDS


def _merge_caption_pair(
    left: TranscriptSegmentTiming,
    right: TranscriptSegmentTiming,
) -> TranscriptSegmentTiming:
    probabilities = [
        probability
        for probability in (left.average_probability, right.average_probability)
        if probability is not None
    ]
    average_probability = (sum(probabilities) / len(probabilities)) if probabilities else None
    return TranscriptSegmentTiming(
        text=f"{_clean_caption_text(left.text)} {_clean_caption_text(right.text)}".strip(),
        start=left.start,
        end=right.end,
        average_probability=average_probability,
    )


def _should_rebalance_caption_pair(
    current: TranscriptSegmentTiming,
    following: TranscriptSegmentTiming,
) -> bool:
    current_text = _clean_caption_text(current.text)
    following_text = _clean_caption_text(following.text)
    if not current_text or not following_text:
        return False
    if current_text.endswith((".", "!", "?")):
        return False
    current_words = current_text.split()
    following_words = following_text.split()
    if not current_words or not following_words:
        return False
    current_last = _normalize_token(current_words[-1])
    following_first = _normalize_token(following_words[0])
    return (
        current_last in _TRAILING_FRAGMENT_TOKENS
        or following_first in _LEADING_FRAGMENT_TOKENS
        or (len(current_words) <= 4 and not current_text.endswith((".", "!", "?")))
        or (len(following_words) <= 4 and following_first in _LEADING_FRAGMENT_TOKENS)
    )


def _best_rebalanced_caption_pair(
    current: TranscriptSegmentTiming,
    following: TranscriptSegmentTiming,
) -> tuple[TranscriptSegmentTiming, TranscriptSegmentTiming] | None:
    combined_text = f"{_clean_caption_text(current.text)} {_clean_caption_text(following.text)}".strip()
    words = combined_text.split()
    if len(words) < 2:
        return None

    current_word_count = len(_clean_caption_text(current.text).split())
    best_pair = None
    best_score = _caption_pair_score(current.text, following.text)

    for split_index in range(1, len(words)):
        left_text = " ".join(words[:split_index])
        right_text = " ".join(words[split_index:])
        if not left_text or not right_text:
            continue
        if len(_clean_caption_text(left_text)) > _CAPTION_MAX_BLOCK_CHARS:
            continue
        if len(_clean_caption_text(right_text)) > _CAPTION_MAX_BLOCK_CHARS:
            continue
        score = _caption_pair_score(left_text, right_text)
        score -= abs(split_index - current_word_count) / 6.0
        if score <= best_score:
            continue
        best_score = score
        best_pair = (left_text, right_text)

    if best_pair is None:
        return None

    left_text, right_text = best_pair
    left_ratio = len(left_text.split()) / max(1, len(words))
    split_time = current.start + ((following.end - current.start) * left_ratio)
    split_time = min(max(split_time, current.start + 0.2), following.end - 0.2)
    probabilities = [
        probability
        for probability in (current.average_probability, following.average_probability)
        if probability is not None
    ]
    average_probability = (sum(probabilities) / len(probabilities)) if probabilities else None
    return (
        TranscriptSegmentTiming(
            text=_wrap_caption_block_lines(left_text),
            start=current.start,
            end=split_time,
            average_probability=average_probability,
        ),
        TranscriptSegmentTiming(
            text=_wrap_caption_block_lines(right_text),
            start=split_time,
            end=following.end,
            average_probability=average_probability,
        ),
    )


def _caption_pair_score(left_text: str, right_text: str) -> float:
    return _caption_text_score(left_text) + _caption_text_score(right_text)


def _caption_text_score(text: str) -> float:
    cleaned = _clean_caption_text(text)
    wrapped = _wrap_caption_block_lines(cleaned)
    lines = [line.strip() for line in wrapped.splitlines() if line.strip()]
    if not lines:
        return float("-inf")
    if len(lines) > _CAPTION_MAX_LINES:
        return float("-inf")
    score = 0.0
    for line in lines:
        if len(line) > _CAPTION_MAX_LINE_CHARS:
            return float("-inf")
        score -= abs(len(line) - _CAPTION_TARGET_LINE_CHARS) / 10.0
    score += _caption_fragment_layout_score(lines)
    words = cleaned.split()
    if words:
        first_word = _normalize_token(words[0])
        last_word = _normalize_token(words[-1])
        if first_word in _LEADING_FRAGMENT_TOKENS:
            score -= 8.0
        if last_word in _TRAILING_FRAGMENT_TOKENS:
            score -= 8.0
    if len(words) <= 3 and not cleaned.endswith((".", "!", "?")):
        score -= 4.0
    return score


def _is_short_caption_stub(segment: TranscriptSegmentTiming) -> bool:
    text = _clean_caption_text(segment.text)
    if not text:
        return False
    words = text.split()
    duration = max(0.0, segment.end - segment.start)
    first_word = _normalize_token(words[0]) if words else ""
    last_word = _normalize_token(words[-1]) if words else ""
    if duration < 0.35:
        return True
    if re.fullmatch(r"(section\s+)?\d+[.)]?", text.strip(), flags=re.IGNORECASE):
        return True
    if len(words) <= 2 and re.fullmatch(r"[\d\W]+", text):
        return True
    if duration <= _CAPTION_STUB_MAX_DURATION_SECONDS and len(words) <= _CAPTION_STUB_MAX_WORDS:
        if text[:1].islower() or first_word in _LEADING_FRAGMENT_TOKENS or last_word in _TRAILING_FRAGMENT_TOKENS:
            return True
    return False


def _should_attach_stub_to_next(segment: TranscriptSegmentTiming) -> bool:
    text = _clean_caption_text(segment.text)
    if not text:
        return False
    words = text.split()
    if not words:
        return False
    first_word = _normalize_token(words[0])
    last_word = _normalize_token(words[-1])
    if re.fullmatch(r"(section\s+)?\d+[.)]?", text.strip(), flags=re.IGNORECASE):
        return False
    return (
        not text.endswith((".", "!", "?"))
        or first_word in _LEADING_FRAGMENT_TOKENS
        or last_word in _TRAILING_FRAGMENT_TOKENS
        or text[:1].islower()
    )


def _split_or_wrap_caption_segment(
    segment: TranscriptSegmentTiming,
) -> list[TranscriptSegmentTiming]:
    text = _clean_caption_text(segment.text)
    if not text:
        return []
    if len(text) <= _CAPTION_MAX_BLOCK_CHARS:
        return [
            TranscriptSegmentTiming(
                text=_wrap_caption_block_lines(text),
                start=segment.start,
                end=segment.end,
                average_probability=segment.average_probability,
            )
        ]
    return _split_sentence_unit_into_cues(
        text,
        start=segment.start,
        end=segment.end,
        average_probability=segment.average_probability,
    )


def _boundary_overlap_tokens(previous_text: str, next_text: str) -> int:
    previous_tokens = previous_text.split()
    next_tokens = next_text.split()
    max_overlap = min(_BOUNDARY_DEDUPE_MAX_TOKENS, len(previous_tokens), len(next_tokens))
    for size in range(max_overlap, 0, -1):
        prev_tail = [_normalize_token(token) for token in previous_tokens[-size:]]
        next_head = [_normalize_token(token) for token in next_tokens[:size]]
        if any(not token for token in prev_tail + next_head):
            continue
        if prev_tail == next_head:
            if size == 1 and previous_tokens[-1] == next_tokens[0] and previous_tokens[-1].istitle():
                return 0
            return size
    return 0


def _segment_overlap(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    overlap = max(0.0, min(end_a, end_b) - max(start_a, start_b))
    if overlap <= 0.0:
        return 0.0
    span = max(0.05, max(end_a, end_b) - min(start_a, start_b))
    return overlap / span


def _render_caption_document(segments: list[TranscriptSegmentTiming], *, caption_format: CaptionFormat) -> str:
    rows = [(index, segment) for index, segment in enumerate(segments, start=1) if _clean_caption_text(segment.text)]
    if caption_format == CaptionFormat.VTT:
        blocks = ["WEBVTT", ""]
        for index, segment in rows:
            start_text = _format_caption_timestamp(segment.start, separator=".")
            end_text = _format_caption_timestamp(max(segment.end, segment.start + 0.2), separator=".")
            text = str(segment.text or "").strip()
            blocks.extend([str(index), f"{start_text} --> {end_text}", text, ""])
        return "\n".join(blocks).rstrip() + "\n"

    blocks: list[str] = []
    for index, segment in rows:
        start_text = _format_caption_timestamp(segment.start, separator=",")
        end_text = _format_caption_timestamp(max(segment.end, segment.start + 0.2), separator=",")
        text = str(segment.text or "").strip()
        blocks.extend([str(index), f"{start_text} --> {end_text}", text, ""])
    return "\n".join(blocks).rstrip() + ("\n" if blocks else "")


def _format_caption_document(segments: list[TranscriptSegmentTiming], *, caption_format: CaptionFormat) -> str:
    return _render_caption_document(
        _compose_accessible_caption_blocks(segments),
        caption_format=caption_format,
    )


def _clean_caption_text(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"\s*-\s*([A-Za-z])", r"-\1", cleaned)
    words = cleaned.split()
    if len(words) >= 2:
        first = _normalize_token(words[0])
        second = _normalize_token(words[1])
        if first and first == second and first in _LEAD_REPEAT_NORMALIZE_TOKENS:
            words.pop(1)
            cleaned = " ".join(words)
    return cleaned


def _format_caption_timestamp(seconds: float, *, separator: str) -> str:
    safe_seconds = max(0.0, float(seconds))
    total_milliseconds = int(round(safe_seconds * 1000.0))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{milliseconds:03d}"
