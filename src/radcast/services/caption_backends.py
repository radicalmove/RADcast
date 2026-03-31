"""Shared caption backend contracts and normalized transcription result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.util import find_spec
from pathlib import Path
import threading
from typing import Protocol


@dataclass(frozen=True)
class CaptionWord:
    text: str
    start: float
    end: float
    probability: float | None = None

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError("caption word timing range must be non-negative and ordered")


@dataclass(frozen=True)
class CaptionSegment:
    start: float
    end: float
    text: str
    average_probability: float | None = None
    words: tuple[CaptionWord, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError("caption segment timing range must be non-negative and ordered")


@dataclass(frozen=True)
class CaptionTranscriptionResult:
    text: str
    segments: list[CaptionSegment]
    words: list[CaptionWord]
    model_id: str


class CaptionBackend(Protocol):
    id: str

    def capability_status(self) -> tuple[bool, str]: ...

    def transcribe_chunk(
        self,
        audio_path: Path,
        *,
        preserve_fillers: bool,
        model_size: str | None = None,
        beam_size: int | None = None,
        condition_on_previous_text: bool = False,
        initial_prompt: str | None = None,
    ) -> CaptionTranscriptionResult: ...


class FasterWhisperCaptionBackend:
    id = "faster_whisper"

    def __init__(
        self,
        *,
        default_model_size: str,
        device: str,
        compute_type: str,
        transcribe_language: str,
        default_beam_size: int,
    ) -> None:
        self.default_model_size = str(default_model_size or "").strip() or "small"
        self.device = str(device or "").strip() or "auto"
        self.compute_type = str(compute_type or "").strip() or "int8"
        self.transcribe_language = str(transcribe_language or "").strip().lower()
        self.default_beam_size = max(1, int(default_beam_size or 1))
        self._models: dict[str, object] = {}
        self._model_lock = threading.Lock()

    def capability_status(self) -> tuple[bool, str]:
        if find_spec("faster_whisper") is None:
            return False, "Install faster-whisper to enable local caption transcription."
        return True, "faster-whisper is available."

    def load_model(self, model_size: str | None = None):
        resolved_model_size = str(model_size or self.default_model_size).strip() or self.default_model_size
        cached = self._models.get(resolved_model_size)
        if cached is not None:
            return cached
        with self._model_lock:
            cached = self._models.get(resolved_model_size)
            if cached is not None:
                return cached
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("faster-whisper is required for caption transcription") from exc
            self._evict_cached_models_except(resolved_model_size)
            model = WhisperModel(resolved_model_size, device=self.device, compute_type=self.compute_type)
            self._models = {resolved_model_size: model}
            return model

    def transcribe_chunk(
        self,
        audio_path: Path,
        *,
        preserve_fillers: bool,
        model_size: str | None = None,
        beam_size: int | None = None,
        condition_on_previous_text: bool = False,
        initial_prompt: str | None = None,
    ) -> CaptionTranscriptionResult:
        resolved_model_size = str(model_size or self.default_model_size).strip() or self.default_model_size
        model = self.load_model(resolved_model_size)
        return self.transcribe_loaded_model(
            model,
            audio_path,
            preserve_fillers=preserve_fillers,
            model_id=resolved_model_size,
            beam_size=beam_size,
            condition_on_previous_text=condition_on_previous_text,
            initial_prompt=initial_prompt,
        )

    def transcribe_loaded_model(
        self,
        model,
        audio_path: Path,
        *,
        preserve_fillers: bool,
        model_id: str | None = None,
        beam_size: int | None = None,
        condition_on_previous_text: bool = False,
        initial_prompt: str | None = None,
    ) -> CaptionTranscriptionResult:
        kwargs = {
            "beam_size": max(1, int(beam_size or self.default_beam_size)),
            "word_timestamps": True,
            "vad_filter": not preserve_fillers,
            "condition_on_previous_text": condition_on_previous_text,
        }
        prompt_text = initial_prompt
        if prompt_text:
            kwargs["initial_prompt"] = prompt_text
        if self.transcribe_language and self.transcribe_language != "auto":
            kwargs["language"] = self.transcribe_language
        segment_iter, _info = model.transcribe(str(audio_path), **kwargs)
        segments: list[CaptionSegment] = []
        words: list[CaptionWord] = []
        text_parts: list[str] = []
        for seg in segment_iter:
            start = max(0.0, float(seg.start))
            end = max(start, float(seg.end))
            text = str(seg.text or "").strip()
            probabilities: list[float] = []
            segment_words: list[CaptionWord] = []
            for word in seg.words or []:
                probability = float(word.probability) if word.probability is not None else None
                if probability is not None:
                    probabilities.append(probability)
                normalized_word = CaptionWord(
                    text=str(word.word or "").strip(),
                    start=max(0.0, float(word.start)),
                    end=max(max(0.0, float(word.start)), float(word.end)),
                    probability=probability,
                )
                segment_words.append(normalized_word)
                words.append(normalized_word)
            segment_text = " ".join(word.text for word in segment_words if word.text).strip() or text
            if segment_text:
                text_parts.append(segment_text)
            segments.append(
                CaptionSegment(
                    start=start,
                    end=end,
                    text=segment_text,
                    average_probability=(sum(probabilities) / len(probabilities)) if probabilities else None,
                    words=tuple(segment_words),
                )
            )
        return CaptionTranscriptionResult(
            text=" ".join(text_parts).strip(),
            segments=segments,
            words=words,
            model_id=str(model_id or self.default_model_size),
        )

    def _evict_cached_models_except(self, keep_model_size: str) -> None:
        if not self._models:
            return
        stale_keys = [key for key in self._models.keys() if key != keep_model_size]
        if not stale_keys:
            return
        for key in stale_keys:
            self._models.pop(key, None)
