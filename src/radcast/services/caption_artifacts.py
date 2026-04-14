"""Helpers for parsing and editing caption artifact files."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class VttCue:
    cue_index: int
    identifier: str | None
    start_seconds: float
    end_seconds: float
    text: str


@dataclass(frozen=True)
class CueEdit:
    cue_index: int
    text: str | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None


def load_vtt_cues(caption_path: Path) -> list[VttCue]:
    lines = caption_path.read_text(encoding="utf-8").splitlines()
    cues: list[VttCue] = []
    index = 0
    cue_index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line or line.upper() == "WEBVTT":
            index += 1
            continue

        identifier: str | None = None
        timestamp_line = line
        if "-->" not in timestamp_line and index + 1 < len(lines):
            identifier = line
            timestamp_line = lines[index + 1].strip()
            index += 1
        if "-->" not in timestamp_line:
            index += 1
            continue

        start_raw, end_raw = [part.strip() for part in timestamp_line.split("-->", 1)]
        start_seconds = _timestamp_to_seconds(start_raw)
        end_seconds = _timestamp_to_seconds(end_raw)
        index += 1

        text_lines: list[str] = []
        while index < len(lines):
            cue_line = lines[index]
            if not cue_line.strip():
                break
            if "-->" in cue_line:
                break
            text_lines.append(cue_line.strip())
            index += 1
        cues.append(
            VttCue(
                cue_index=cue_index,
                identifier=identifier,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                text=" ".join(text_lines).strip(),
            )
        )
        cue_index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1
    return cues


def apply_cue_edit(cues: list[VttCue], edit: CueEdit) -> list[VttCue]:
    updated = list(cues)
    cue = next((item for item in updated if item.cue_index == edit.cue_index), None)
    if cue is None:
        raise IndexError(f"cue {edit.cue_index} not found")
    start_seconds = cue.start_seconds if edit.start_seconds is None else float(edit.start_seconds)
    end_seconds = cue.end_seconds if edit.end_seconds is None else float(edit.end_seconds)
    if end_seconds <= start_seconds:
        raise ValueError("cue end must be greater than cue start")
    text = cue.text if edit.text is None else str(edit.text).strip()
    updated[edit.cue_index] = replace(
        cue,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        text=text,
    )
    return updated


def save_vtt_cues(caption_path: Path, cues: list[VttCue]) -> None:
    blocks = ["WEBVTT", ""]
    for sequence_index, cue in enumerate(cues, start=1):
        identifier = cue.identifier or str(sequence_index)
        blocks.append(str(identifier))
        blocks.append(f"{_format_timestamp(cue.start_seconds)} --> {_format_timestamp(cue.end_seconds)}")
        blocks.append(str(cue.text or "").strip())
        blocks.append("")
    caption_path.write_text("\n".join(blocks).rstrip() + "\n", encoding="utf-8")


def absolute_cue_times(*, cue_start_seconds: float, cue_end_seconds: float, clip_start_seconds: float | None = None) -> tuple[float, float]:
    offset = float(clip_start_seconds or 0.0)
    return (offset + float(cue_start_seconds), offset + float(cue_end_seconds))


def relative_cue_times(
    *,
    absolute_start_seconds: float,
    absolute_end_seconds: float,
    clip_start_seconds: float | None = None,
) -> tuple[float, float]:
    offset = float(clip_start_seconds or 0.0)
    start_seconds = max(0.0, float(absolute_start_seconds) - offset)
    end_seconds = max(start_seconds, float(absolute_end_seconds) - offset)
    return (start_seconds, end_seconds)


def _timestamp_to_seconds(raw_value: str) -> float:
    value = raw_value.strip().replace(",", ".")
    hours, minutes, seconds_fraction = value.split(":")
    seconds, milliseconds = seconds_fraction.split(".")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(milliseconds) / 1000.0


def _format_timestamp(seconds: float) -> str:
    safe_seconds = max(0.0, float(seconds))
    total_milliseconds = int(round(safe_seconds * 1000.0))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"
