"""Shared caption backend contracts and normalized transcription result types."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from importlib.util import find_spec
from pathlib import Path
import shutil
import subprocess
import tempfile
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


class WhisperCppCaptionBackend:
    id = "whispercpp"

    def __init__(
        self,
        *,
        default_model_size: str,
        transcribe_language: str,
        default_beam_size: int,
        binary_path: str | None = None,
        model_dir: str | None = None,
        use_gpu: bool = True,
    ) -> None:
        self.default_model_size = str(default_model_size or "").strip() or "small"
        self.transcribe_language = str(transcribe_language or "").strip().lower() or "en"
        self.default_beam_size = max(1, int(default_beam_size or 1))
        self.binary_path = str(binary_path or os.environ.get("RADCAST_WHISPERCPP_BIN", "")).strip() or None
        self.model_dir = str(model_dir or os.environ.get("RADCAST_WHISPERCPP_MODEL_DIR", "")).strip() or None
        self.use_gpu = bool(use_gpu)
        self._models: dict[str, object] = {}

    def capability_status(self) -> tuple[bool, str]:
        binary = self._resolve_binary()
        if binary is None:
            return False, "Install whisper.cpp and make whisper-cli available to enable macOS local caption acceleration."
        model_path = self._resolve_model_path(self.default_model_size)
        if model_path is None:
            return False, f"whisper.cpp is available, but the ggml model for '{self.default_model_size}' was not found."
        return True, f"whisper.cpp is available via {binary}."

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
        binary = self._resolve_binary()
        if binary is None:
            raise RuntimeError("whisper.cpp binary is unavailable")
        resolved_model_size = str(model_size or self.default_model_size).strip() or self.default_model_size
        model_path = self._resolve_model_path(resolved_model_size)
        if model_path is None:
            raise RuntimeError(f"whisper.cpp model '{resolved_model_size}' is unavailable")
        with tempfile.TemporaryDirectory(prefix="radcast_whispercpp_") as tmp:
            output_base = Path(tmp) / "transcript"
            cmd = [
                binary,
                "--model",
                str(model_path),
                "--file",
                str(audio_path),
                "--output-json-full",
                "--output-file",
                str(output_base),
                "--beam-size",
                str(max(1, int(beam_size or self.default_beam_size))),
                "--language",
                self.transcribe_language,
                "--no-prints",
            ]
            if not self.use_gpu:
                cmd.append("--no-gpu")
            if initial_prompt:
                cmd.extend(["--prompt", initial_prompt])
            if not condition_on_previous_text:
                cmd.extend(["--max-context", "0"])
            completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if completed.returncode != 0:
                error_text = completed.stderr.strip() or completed.stdout.strip() or "unknown whisper.cpp failure"
                raise RuntimeError(error_text)
            json_path = output_base.with_suffix(".json")
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        return self._parse_json_payload(payload, model_id=resolved_model_size)

    def _resolve_binary(self) -> str | None:
        if self.binary_path:
            path = Path(self.binary_path).expanduser()
            return str(path) if path.exists() else None
        resolved = shutil.which("whisper-cli")
        return resolved or None

    def _resolve_model_path(self, model_size: str) -> Path | None:
        explicit = os.environ.get("RADCAST_WHISPERCPP_MODEL_PATH", "").strip()
        if explicit:
            path = Path(explicit).expanduser()
            return path if path.exists() else None
        if not self.model_dir:
            return None
        path = Path(self.model_dir).expanduser() / f"ggml-{model_size}.bin"
        return path if path.exists() else None

    def _parse_json_payload(self, payload: dict[str, object], *, model_id: str) -> CaptionTranscriptionResult:
        raw_segments = payload.get("transcription") or payload.get("segments") or []
        segments: list[CaptionSegment] = []
        words: list[CaptionWord] = []
        text_parts: list[str] = []
        if not isinstance(raw_segments, list):
            raw_segments = []
        for entry in raw_segments:
            if not isinstance(entry, dict):
                continue
            text = str(entry.get("text") or "").strip()
            start = self._timestamp_seconds(entry.get("offsets", {}).get("from") if isinstance(entry.get("offsets"), dict) else entry.get("t0"))
            end = self._timestamp_seconds(entry.get("offsets", {}).get("to") if isinstance(entry.get("offsets"), dict) else entry.get("t1"))
            raw_words = entry.get("words") if isinstance(entry.get("words"), list) else []
            normalized_words: list[CaptionWord] = []
            probabilities: list[float] = []
            for word_entry in raw_words:
                if not isinstance(word_entry, dict):
                    continue
                word_text = str(word_entry.get("text") or word_entry.get("word") or "").strip()
                word_start = self._timestamp_seconds(word_entry.get("t0") or word_entry.get("start") or word_entry.get("from"))
                word_end = self._timestamp_seconds(word_entry.get("t1") or word_entry.get("end") or word_entry.get("to"))
                probability_raw = word_entry.get("p") if word_entry.get("p") is not None else word_entry.get("probability")
                probability = float(probability_raw) if probability_raw is not None else None
                if probability is not None:
                    probabilities.append(probability)
                normalized_word = CaptionWord(
                    text=word_text,
                    start=word_start,
                    end=max(word_start, word_end),
                    probability=probability,
                )
                normalized_words.append(normalized_word)
                words.append(normalized_word)
            segment_text = " ".join(word.text for word in normalized_words if word.text).strip() or text
            if segment_text:
                text_parts.append(segment_text)
            segments.append(
                CaptionSegment(
                    start=start,
                    end=max(start, end),
                    text=segment_text,
                    average_probability=(sum(probabilities) / len(probabilities)) if probabilities else None,
                    words=tuple(normalized_words),
                )
            )
        return CaptionTranscriptionResult(
            text=" ".join(text_parts).strip(),
            segments=segments,
            words=words,
            model_id=model_id,
        )

    @staticmethod
    def _timestamp_seconds(value: object) -> float:
        if value is None:
            return 0.0
        return max(0.0, float(value) / 100.0)
