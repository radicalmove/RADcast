"""Speech-aware post-processing for long silences and filler words."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Callable

import numpy as np

from radcast.exceptions import EnhancementRuntimeError, JobCancelledError
from radcast.models import FillerRemovalMode, OutputFormat
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
_AGGRESSIVE_TRANSCRIBE_WINDOW_SECONDS = 4.0
_AGGRESSIVE_TRANSCRIBE_OVERLAP_SECONDS = 1.0
_AGGRESSIVE_FILLER_PROMPT = (
    "Transcribe all spoken disfluencies exactly, including um, ums, uh, uhh, ah, ahh, erm, mm, and hesitation sounds."
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
        self.model_size = os.environ.get("RADCAST_SPEECH_CLEANUP_MODEL", "small").strip() or "small"
        self.device = os.environ.get("RADCAST_SPEECH_CLEANUP_DEVICE", "auto").strip() or "auto"
        self.compute_type = os.environ.get("RADCAST_SPEECH_CLEANUP_COMPUTE_TYPE", "int8").strip() or "int8"
        self.beam_size = max(1, int(os.environ.get("RADCAST_SPEECH_CLEANUP_BEAM_SIZE", "3")))
        self._model = None
        self._model_lock = threading.Lock()

    @staticmethod
    def cleanup_requested(max_silence_seconds: float | None, remove_filler_words: bool) -> bool:
        return max_silence_seconds is not None or bool(remove_filler_words)

    def capability_status(self) -> tuple[bool, str]:
        if find_spec("faster_whisper") is None:
            return False, "Install faster-whisper to enable long-silence trimming and filler-word cleanup."
        return True, f"Speech cleanup is available with faster-whisper ({self.model_size})."

    def estimate_runtime_seconds(
        self,
        duration_seconds: float,
        *,
        remove_filler_words: bool,
        filler_removal_mode: FillerRemovalMode = FillerRemovalMode.AGGRESSIVE,
    ) -> int:
        safe_duration = max(1.0, float(duration_seconds))
        normalized_mode = _normalize_filler_mode(filler_removal_mode)
        if remove_filler_words:
            if normalized_mode == FillerRemovalMode.AGGRESSIVE:
                base_seconds = 18.0
                per_second = 0.55
            else:
                base_seconds = 11.0
                per_second = 0.32
        else:
            base_seconds = 7.0
            per_second = 0.22
        return max(6, min(int(round(base_seconds + (safe_duration * per_second))), 12 * 60))

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

    def _load_model(self):
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:  # pragma: no cover - availability is checked before runtime use
                raise EnhancementRuntimeError(
                    "faster-whisper is required for speech cleanup. Install with 'pip install -e .'."
                ) from exc
            self._model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
        return self._model

    def _transcribe_file(self, model, audio_path: Path, *, preserve_fillers: bool) -> list[object]:
        kwargs = {
            "beam_size": self.beam_size,
            "word_timestamps": True,
            "vad_filter": not preserve_fillers,
            "condition_on_previous_text": False,
        }
        if preserve_fillers:
            kwargs["initial_prompt"] = _AGGRESSIVE_FILLER_PROMPT
        segment_iter, _info = model.transcribe(str(audio_path), **kwargs)
        return list(segment_iter)

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
    ) -> tuple[list[TranscriptWordTiming], list[TranscriptSegmentTiming]]:
        normalized_mode = _normalize_filler_mode(filler_removal_mode)
        if remove_filler_words and normalized_mode == FillerRemovalMode.AGGRESSIVE:
            return self._transcribe_windowed_timeline(
                audio_path,
                total_duration=total_duration,
                started_at=started_at,
                cleanup_eta_seconds=cleanup_eta_seconds,
                on_stage=on_stage,
            )

        model = self._load_model()
        transcribed_segments = self._transcribe_file(model, audio_path, preserve_fillers=False)

        words: list[TranscriptWordTiming] = []
        segments: list[TranscriptSegmentTiming] = []
        last_progress_emit_at = 0.0
        for seg in transcribed_segments:
            start = max(0.0, float(seg.start))
            end = max(start, float(seg.end))
            text = str(seg.text or "").strip()
            segments.append(TranscriptSegmentTiming(text=text, start=start, end=end))
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
                        "Transcribing speech timing for cleanup.",
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
    ) -> tuple[list[TranscriptWordTiming], list[TranscriptSegmentTiming]]:
        model = self._load_model()
        waveform, sample_rate = _read_pcm16_wav(audio_path)
        total_duration = max(0.0, float(total_duration))
        if total_duration <= 0.0:
            return [], []

        window_seconds = min(max(_AGGRESSIVE_TRANSCRIBE_WINDOW_SECONDS, 1.0), total_duration)
        overlap_seconds = min(_AGGRESSIVE_TRANSCRIBE_OVERLAP_SECONDS, max(0.0, window_seconds / 2.0))
        step_seconds = max(0.5, window_seconds - overlap_seconds)
        words: list[TranscriptWordTiming] = []
        segments: list[TranscriptSegmentTiming] = []

        with tempfile.TemporaryDirectory(prefix="radcast_cleanup_transcribe_") as tmp:
            tmp_path = Path(tmp)
            window_start = 0.0
            window_index = 0
            while True:
                window_end = min(total_duration, window_start + window_seconds)
                start_idx = max(0, min(len(waveform), int(round(window_start * sample_rate))))
                end_idx = max(start_idx, min(len(waveform), int(round(window_end * sample_rate))))
                window_path = tmp_path / f"window_{int(round(window_start * 1000)):06d}.wav"
                _write_pcm16_wav(window_path, waveform[start_idx:end_idx], sample_rate=sample_rate)
                transcribed_segments = self._transcribe_file(model, window_path, preserve_fillers=True)

                left_guard_seconds = 0.0 if window_index == 0 else overlap_seconds / 2.0
                right_guard_seconds = 0.0 if window_end >= total_duration - 1e-6 else overlap_seconds / 2.0
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
                    on_stage(
                        progress,
                        "Transcribing speech timing for cleanup.",
                        _transcription_eta_seconds(
                            elapsed_seconds=max(0.0, time.monotonic() - started_at),
                            cleanup_eta_seconds=cleanup_eta_seconds,
                            coverage=coverage,
                        ),
                    )

                if window_end >= total_duration - 1e-6:
                    break
                window_start = min(total_duration, window_start + step_seconds)
                window_index += 1

        return _dedupe_transcript_words(words), _dedupe_transcript_segments(segments)

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
        remaining = projected_total - safe_elapsed
    else:
        remaining = float(cleanup_eta_seconds) - safe_elapsed
    return max(2, int(round(max(1.0, remaining))))


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
            words.append(
                TranscriptWordTiming(
                    text=str(word.word or "").strip(),
                    start=window_offset_seconds + max(word_start, keep_start_seconds),
                    end=window_offset_seconds + min(word_end, keep_end_seconds),
                    probability=float(word.probability) if word.probability is not None else None,
                )
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
