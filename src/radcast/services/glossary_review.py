"""Glossary review candidate extraction for caption accessibility failures."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from radcast.services.glossary_store import normalize_glossary_term

_TIMESTAMP_RE = re.compile(
    r"^(?P<start>\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(?P<end>\d{2}:\d{2}:\d{2}\.\d{3})(?:\s*\|\s*confidence\s*(?P<confidence>.+))?$"
)
_REASON_PREFIX = "probable critical term miss:"


@dataclass(frozen=True)
class ReviewCue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class ReviewFlag:
    start: float
    end: float
    term: str
    reason: str
    cue_text: str


@dataclass(frozen=True)
class GlossaryReviewCandidate:
    candidate_id: str
    term: str
    normalized_term: str
    reason: str
    previous_context: str
    flagged_context: str
    next_context: str
    already_known: bool


def extract_glossary_review_candidates(
    *,
    caption_path: Path,
    review_path: Path,
    active_terms: list[str] | tuple[str, ...] | None = None,
) -> list[GlossaryReviewCandidate]:
    cues = _parse_vtt_cues(caption_path)
    flags = _parse_review_flags(review_path)
    known_terms = {normalize_glossary_term(term) for term in (active_terms or ()) if normalize_glossary_term(term)}

    candidates: list[GlossaryReviewCandidate] = []
    seen: set[tuple[str, float, float]] = set()
    for flag in flags:
        normalized_term = normalize_glossary_term(flag.term)
        if not normalized_term:
            continue
        if (normalized_term, float(flag.start), float(flag.end)) in seen:
            continue
        seen.add((normalized_term, float(flag.start), float(flag.end)))
        previous_context, flagged_context, next_context = _cue_context_for_flag(cues, flag.start, flag.end)
        candidates.append(
            GlossaryReviewCandidate(
                candidate_id=f"{normalized_term}:{int(round(flag.start * 1000))}:{int(round(flag.end * 1000))}",
                term=flag.term,
                normalized_term=normalized_term,
                reason=flag.reason,
                previous_context=previous_context,
                flagged_context=flagged_context,
                next_context=next_context,
                already_known=normalized_term in known_terms,
            )
        )

    candidates.sort(key=lambda item: (item.candidate_id, item.normalized_term, item.term.casefold()))
    return candidates


def _parse_review_flags(review_path: Path) -> list[ReviewFlag]:
    try:
        lines = review_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []

    flags: list[ReviewFlag] = []
    index = 0
    while index < len(lines):
        match = _TIMESTAMP_RE.match(lines[index].strip())
        if not match:
            index += 1
            continue
        start = _timestamp_to_seconds(match.group("start"))
        end = _timestamp_to_seconds(match.group("end"))
        index += 1

        reason_line = ""
        cue_lines: list[str] = []
        while index < len(lines):
            current = lines[index].strip()
            if not current:
                index += 1
                if cue_lines:
                    break
                continue
            if current.startswith("Reason:"):
                reason_line = current
                index += 1
                continue
            cue_lines.append(current)
            index += 1
        reason = reason_line.removeprefix("Reason:").strip()
        if not reason.startswith(_REASON_PREFIX):
            continue
        term = reason.removeprefix(_REASON_PREFIX).strip()
        if not term:
            continue
        flags.append(
            ReviewFlag(
                start=start,
                end=end,
                term=term,
                reason=reason,
                cue_text=" ".join(cue_lines).strip(),
            )
        )
    return flags


def _parse_vtt_cues(caption_path: Path) -> list[ReviewCue]:
    try:
        lines = caption_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []

    cues: list[ReviewCue] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line or line.upper() == "WEBVTT":
            index += 1
            continue
        if "-->" not in line:
            index += 1
            continue
        match = _TIMESTAMP_RE.match(line)
        if not match:
            index += 1
            continue
        start = _timestamp_to_seconds(match.group("start"))
        end = _timestamp_to_seconds(match.group("end"))
        index += 1
        text_lines: list[str] = []
        while index < len(lines):
            cue_line = lines[index].strip()
            if not cue_line:
                break
            if "-->" in cue_line and _TIMESTAMP_RE.match(cue_line):
                break
            text_lines.append(cue_line)
            index += 1
        cues.append(ReviewCue(start=start, end=end, text=" ".join(text_lines).strip()))
        while index < len(lines) and not lines[index].strip():
            index += 1
    return cues


def _cue_context_for_flag(cues: list[ReviewCue], start: float, end: float) -> tuple[str, str, str]:
    if not cues:
        return "", "", ""
    overlaps = [cue for cue in cues if _overlap(cue.start, cue.end, start, end) > 0.0]
    if overlaps:
        first = overlaps[0]
        last = overlaps[-1]
        first_index = cues.index(first)
        last_index = cues.index(last)
    else:
        midpoint = (start + end) / 2.0
        nearest_index = min(
            range(len(cues)),
            key=lambda idx: abs(((cues[idx].start + cues[idx].end) / 2.0) - midpoint),
        )
        first_index = last_index = nearest_index

    previous_context = cues[first_index - 1].text if first_index > 0 else ""
    flagged_context = " ".join(cue.text for cue in cues[first_index : last_index + 1] if cue.text).strip()
    next_context = cues[last_index + 1].text if last_index + 1 < len(cues) else ""
    return previous_context, flagged_context, next_context


def _overlap(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    return max(0.0, min(end_a, end_b) - max(start_a, start_b))


def _timestamp_to_seconds(value: str) -> float:
    hours, minutes, seconds_fraction = value.split(":")
    seconds, fraction = seconds_fraction.split(".")
    return (
        (int(hours) * 3600)
        + (int(minutes) * 60)
        + int(seconds)
        + (int(fraction) / 1000.0)
    )
