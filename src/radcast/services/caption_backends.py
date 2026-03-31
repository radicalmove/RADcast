"""Shared caption backend contracts and normalized transcription result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
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
        beam_size: int | None = None,
        condition_on_previous_text: bool = False,
        initial_prompt: str | None = None,
    ) -> CaptionTranscriptionResult: ...
