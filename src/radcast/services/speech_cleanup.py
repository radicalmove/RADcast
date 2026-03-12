"""Speech-aware post-processing for long silences and filler words."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
import wave
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Callable

import numpy as np

from radcast.exceptions import EnhancementRuntimeError, JobCancelledError
from radcast.models import OutputFormat
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
_FILLER_MAX_DURATION_SECONDS = 1.15
_FILLER_MIN_PROBABILITY = 0.45
_CUT_CROSSFADE_SECONDS = 0.012
_TOKEN_RE = re.compile(r"[^a-z']+")


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


class SpeechCleanupService:
    def __init__(self) -> None:
        self.model_size = os.environ.get("RADCAST_SPEECH_CLEANUP_MODEL", "base").strip() or "base"
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

    def estimate_runtime_seconds(self, duration_seconds: float, *, remove_filler_words: bool) -> int:
        safe_duration = max(1.0, float(duration_seconds))
        base_seconds = 8.0 if remove_filler_words else 6.0
        per_second = 0.26 if remove_filler_words else 0.18
        return max(6, min(int(round(base_seconds + (safe_duration * per_second))), 12 * 60))

    def cleanup_audio_file(
        self,
        *,
        audio_path: Path,
        output_format: OutputFormat,
        max_silence_seconds: float | None,
        remove_filler_words: bool,
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
        if on_stage:
            on_stage(
                0.965,
                "Analyzing speech timing for pause cleanup.",
                self.estimate_runtime_seconds(input_duration, remove_filler_words=remove_filler_words),
            )

        with tempfile.TemporaryDirectory(prefix="radcast_cleanup_") as tmp:
            tmp_path = Path(tmp)
            analysis_wav = tmp_path / "analysis.wav"
            run_ffmpeg_convert(audio_path, analysis_wav)

            words, segments = self._transcribe_timeline(analysis_wav)

            if cancel_check and cancel_check():
                raise JobCancelledError("job cancelled")

            waveform, sample_rate = _read_pcm16_wav(analysis_wav)
            total_duration = waveform.shape[0] / float(sample_rate) if sample_rate else 0.0
            filler_intervals, filler_count = self._filler_intervals(
                words=words,
                remove_filler_words=remove_filler_words,
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
                    0.985,
                    self._rewrite_detail(silence_count=silence_count, filler_count=filler_count),
                    4,
                )

            edited = _splice_waveform(waveform, sample_rate=sample_rate, removal_intervals=removal_intervals)
            cleaned_wav = tmp_path / "cleaned.wav"
            _write_pcm16_wav(cleaned_wav, edited, sample_rate=sample_rate)

            final_tmp = tmp_path / f"final-output{audio_path.suffix.lower() or '.wav'}"
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

    def _transcribe_timeline(
        self,
        audio_path: Path,
    ) -> tuple[list[TranscriptWordTiming], list[TranscriptSegmentTiming]]:
        model = self._load_model()
        segment_iter, _info = model.transcribe(
            str(audio_path),
            beam_size=self.beam_size,
            word_timestamps=True,
            vad_filter=True,
            condition_on_previous_text=False,
        )

        words: list[TranscriptWordTiming] = []
        segments: list[TranscriptSegmentTiming] = []
        for seg in segment_iter:
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
        return words, segments

    def _filler_intervals(
        self,
        *,
        words: list[TranscriptWordTiming],
        remove_filler_words: bool,
    ) -> tuple[list[tuple[float, float]], int]:
        if not remove_filler_words or not words:
            return [], 0

        intervals: list[tuple[float, float]] = []
        count = 0
        for idx, word in enumerate(words):
            normalized = _normalize_token(word.text)
            if normalized not in _FILLER_WORDS:
                continue

            duration = max(0.0, word.end - word.start)
            if duration < _FILLER_MIN_DURATION_SECONDS or duration > _FILLER_MAX_DURATION_SECONDS:
                continue
            if word.probability is not None and word.probability < _FILLER_MIN_PROBABILITY:
                continue

            prev_end = words[idx - 1].end if idx > 0 else 0.0
            next_start = words[idx + 1].start if idx + 1 < len(words) else word.end
            gap_before = max(0.0, word.start - prev_end)
            gap_after = max(0.0, next_start - word.end)

            if gap_before < 0.08 or gap_after < 0.08:
                continue

            lead_pad = min(0.02, gap_before * 0.4)
            tail_pad = min(0.04, gap_after * 0.4)
            intervals.append((max(0.0, word.start - lead_pad), max(word.start, word.end + tail_pad)))
            count += 1
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
                if treat_fillers_as_removed and normalized in _FILLER_WORDS:
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
    with wave.open(str(path), "rb") as handle:
        sample_rate = handle.getframerate()
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        frames = handle.readframes(handle.getnframes())
    if sample_width != 2:
        raise EnhancementRuntimeError("Speech cleanup expects a PCM16 WAV analysis file.")
    pcm = np.frombuffer(frames, dtype="<i2").astype(np.float32)
    if channels > 1:
        pcm = pcm.reshape(-1, channels)
    else:
        pcm = pcm.reshape(-1, 1)
    return pcm / 32768.0, sample_rate


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
