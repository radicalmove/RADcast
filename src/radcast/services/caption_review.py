"""Review-candidate selection and report formatting for caption triage."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, Sequence

_TOKEN_RE = re.compile(r"[^a-z']+")
_CAPTION_REVIEW_MAX_FLAGS = 24
_LOW_CONFIDENCE_THRESHOLD = 0.45
_TRUNCATION_ENDINGS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "because",
    "before",
    "but",
    "by",
    "for",
    "from",
    "if",
    "in",
    "into",
    "of",
    "on",
    "or",
    "so",
    "than",
    "that",
    "the",
    "to",
    "under",
    "via",
    "when",
    "where",
    "while",
    "with",
    "within",
    "without",
}


class CaptionSegmentLike(Protocol):
    text: str
    start: float
    end: float
    average_probability: float | None


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
        return f"Caption review suggested: {self.low_confidence_segment_count} flagged segment{'s' if self.low_confidence_segment_count != 1 else ''}."


def _clean_caption_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _caption_tokens(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.split(_clean_caption_text(text).lower()) if token]


def _segment_overlap(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    overlap = max(0.0, min(end_a, end_b) - max(start_a, start_b))
    if overlap <= 0.0:
        return 0.0
    span = max(0.05, max(end_a, end_b) - min(start_a, start_b))
    return overlap / span


def _is_probable_duplication(previous: CaptionSegmentLike, current: CaptionSegmentLike) -> bool:
    previous_text = _clean_caption_text(previous.text).lower()
    current_text = _clean_caption_text(current.text).lower()
    if not previous_text or not current_text:
        return False
    if previous_text != current_text:
        return False
    overlap_ratio = _segment_overlap(previous.start, previous.end, current.start, current.end)
    gap_seconds = max(0.0, current.start - previous.end)
    return overlap_ratio >= 0.08 or gap_seconds <= 0.35


def _is_probable_truncation(segment: CaptionSegmentLike) -> bool:
    text = _clean_caption_text(segment.text)
    if not text:
        return False
    lowered = text.lower()
    if lowered.endswith(("...", "…", "-")):
        return True
    tokens = _caption_tokens(text)
    if not tokens:
        return False
    if tokens[-1] in _TRUNCATION_ENDINGS:
        return True
    return False


def _caption_review_reason(
    segments: Sequence[CaptionSegmentLike],
    index: int,
) -> str | None:
    segment = segments[index]
    text = _clean_caption_text(segment.text)
    if not text:
        return None
    if index > 0 and _is_probable_duplication(segments[index - 1], segment):
        return "probable duplication"
    if _is_probable_truncation(segment):
        return "probable truncation"
    probability = segment.average_probability
    if probability is None:
        return None
    if probability < _LOW_CONFIDENCE_THRESHOLD:
        return "probable low confidence"
    return None


def select_review_candidates(segments: Sequence[CaptionSegmentLike]) -> list[CaptionReviewFlag]:
    clean_segments = [segment for segment in segments if _clean_caption_text(segment.text)]
    flagged_segments: list[CaptionReviewFlag] = []
    for index, segment in enumerate(clean_segments):
        reason = _caption_review_reason(clean_segments, index)
        if not reason:
            continue
        flagged_segments.append(
            CaptionReviewFlag(
                start=segment.start,
                end=segment.end,
                text=_clean_caption_text(segment.text),
                average_probability=segment.average_probability,
                reason=reason,
            )
        )
    return flagged_segments[:_CAPTION_REVIEW_MAX_FLAGS]


def build_caption_quality_report(segments: Sequence[CaptionSegmentLike]) -> CaptionQualityReport:
    clean_segments = [segment for segment in segments if _clean_caption_text(segment.text)]
    probabilities = [segment.average_probability for segment in clean_segments if segment.average_probability is not None]
    average_probability = (sum(probabilities) / len(probabilities)) if probabilities else None
    flagged_segments = select_review_candidates(clean_segments)
    return CaptionQualityReport(
        average_probability=average_probability,
        low_confidence_segment_count=len(flagged_segments),
        total_segment_count=len(clean_segments),
        flagged_segments=flagged_segments,
        review_recommended=bool(flagged_segments),
    )


def format_caption_review_document(report: CaptionQualityReport) -> str:
    lines = ["RADcast Caption Review", ""]
    if report.average_probability is not None:
        lines.append(f"Average word confidence: {report.average_probability:.0%}")
    lines.append(f"Flagged caption lines: {report.low_confidence_segment_count}")
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
        confidence_text = f"{flag.average_probability:.0%}" if flag.average_probability is not None else "n/a"
        lines.append(f"{start_text} --> {end_text} | confidence {confidence_text}")
        lines.append(f"Reason: {flag.reason}")
        lines.append(flag.text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _format_caption_timestamp(seconds: float, *, separator: str) -> str:
    safe_seconds = max(0.0, float(seconds))
    total_milliseconds = int(round(safe_seconds * 1000.0))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{milliseconds:03d}"
