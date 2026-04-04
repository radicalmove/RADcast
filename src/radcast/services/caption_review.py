"""Review-candidate selection and report formatting for caption triage."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, Sequence

_TOKEN_RE = re.compile(r"[^a-z']+")
_CAPTION_REVIEW_MAX_FLAGS = 18
_LOW_CONFIDENCE_THRESHOLD = 0.45
_FINAL_REVIEW_RESULT_LINE = "this is the final result of the review"
_REVIEW_SYSTEM_PHRASES = (
    "review low-confidence transcript lines carefully",
    "prefer the spoken wording",
    "preserve names and te reo maori",
    "correct likely misheard words rather than paraphrasing",
    "radcast caption review",
    "review these timestamp ranges",
)
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
        flagged_segment_count = len(self.flagged_segments)
        return f"Caption review suggested: {flagged_segment_count} flagged segment{'s' if flagged_segment_count != 1 else ''}."


def _clean_caption_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _normalize_caption_text(text: str) -> str:
    return _clean_caption_text(text).lower().replace("māori", "maori")


def _caption_tokens(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.split(_normalize_caption_text(text)) if token]


def _split_final_review_result_prefix(text: str) -> tuple[bool, str, str | None]:
    cleaned = _clean_caption_text(text)
    if not cleaned:
        return False, "", None
    lowered = cleaned.lower()
    if lowered == _FINAL_REVIEW_RESULT_LINE:
        return True, "", "exact"
    if not lowered.startswith(_FINAL_REVIEW_RESULT_LINE):
        return False, cleaned, None
    next_index = len(_FINAL_REVIEW_RESULT_LINE)
    if next_index >= len(cleaned):
        return True, "", "exact"
    next_char = cleaned[next_index]
    if next_char.isalnum() or next_char == "'":
        return False, cleaned, None
    remainder = cleaned[next_index:].lstrip(" .,!?:;-")
    boundary = "sentence" if next_char in ".!?" else "continuation"
    return True, _clean_caption_text(remainder), boundary


def is_review_system_text(text: str) -> bool:
    normalized = _normalize_caption_text(text)
    if not normalized:
        return False
    normalized_without_trailing_punctuation = normalized.rstrip(" .,!?:;")
    if normalized_without_trailing_punctuation == _FINAL_REVIEW_RESULT_LINE:
        return True
    if normalized_without_trailing_punctuation.startswith("radcast caption review"):
        return True
    if any(normalized_without_trailing_punctuation.startswith(phrase) for phrase in _REVIEW_SYSTEM_PHRASES):
        return True
    matches = int(_FINAL_REVIEW_RESULT_LINE in normalized) + sum(1 for phrase in _REVIEW_SYSTEM_PHRASES if phrase in normalized)
    return matches >= 2


def is_review_echo_candidate(text: str, *, reference_text: str | None = None) -> bool:
    if is_review_system_text(text):
        return True
    has_prefix, remainder, boundary = _split_final_review_result_prefix(text)
    if not has_prefix:
        return False
    if not remainder:
        return True
    _, stripped_reference, _ = _split_final_review_result_prefix(reference_text or "")
    comparison_reference = stripped_reference or _clean_caption_text(reference_text or "")
    reference_tokens = set(_caption_tokens(comparison_reference))
    if not reference_tokens:
        return boundary == "sentence"
    remainder_tokens = set(_caption_tokens(remainder))
    return not bool(remainder_tokens & reference_tokens)


def sanitize_review_candidate_text(text: str, *, reference_text: str | None = None) -> str | None:
    cleaned_text = _clean_caption_text(text)
    if not cleaned_text:
        return None
    if is_review_system_text(cleaned_text):
        return None
    cleaned_reference = _clean_caption_text(reference_text)
    has_prefix, stripped, boundary = _split_final_review_result_prefix(cleaned_text)
    if not has_prefix:
        return cleaned_text
    if not stripped:
        return None
    if is_review_system_text(stripped):
        return None
    reference_has_prefix, stripped_reference, _ = _split_final_review_result_prefix(reference_text or "")
    comparison_reference = stripped_reference or cleaned_reference
    overlap = bool(comparison_reference and set(_caption_tokens(stripped)) & set(_caption_tokens(comparison_reference)))
    if reference_has_prefix:
        if cleaned_reference and cleaned_text == cleaned_reference:
            return cleaned_text if boundary == "continuation" else stripped
        if overlap:
            return stripped
        if boundary == "continuation":
            return cleaned_text
        if is_review_echo_candidate(cleaned_text, reference_text=reference_text):
            return None
        return stripped
    if boundary == "continuation":
        # Continuation-form matches are too ambiguous to strip safely on clean
        # lecture text; only sentence-boundary echoes or already-polluted
        # sources get automatic prefix removal.
        return cleaned_text
    if overlap:
        return stripped
    if is_review_echo_candidate(cleaned_text, reference_text=reference_text):
        return None
    return stripped


def _count_probable_low_confidence_flags(flags: Sequence[CaptionReviewFlag]) -> int:
    return sum(1 for flag in flags if flag.reason == "probable low confidence")


def build_caption_export_quality_report(
    *,
    review_report: CaptionQualityReport,
    export_report: CaptionQualityReport,
) -> CaptionQualityReport:
    merged_flags: list[CaptionReviewFlag] = []
    seen_keys: set[tuple[float, float, str, str]] = set()
    for flag in [*review_report.flagged_segments, *export_report.flagged_segments]:
        key = (float(flag.start), float(flag.end), str(flag.text), str(flag.reason))
        if key in seen_keys:
            continue
        merged_flags.append(flag)
        seen_keys.add(key)
        if len(merged_flags) >= _CAPTION_REVIEW_MAX_FLAGS:
            break
    low_confidence_segment_count = _count_probable_low_confidence_flags(merged_flags)
    return CaptionQualityReport(
        average_probability=export_report.average_probability,
        low_confidence_segment_count=low_confidence_segment_count,
        total_segment_count=export_report.total_segment_count,
        flagged_segments=merged_flags,
        review_recommended=bool(merged_flags),
    )


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


def _select_review_candidates(
    segments: Sequence[CaptionSegmentLike],
    *,
    limit: int | None,
) -> list[CaptionReviewFlag]:
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
    if limit is None:
        return flagged_segments
    return flagged_segments[:max(0, int(limit))]


def select_review_candidates(segments: Sequence[CaptionSegmentLike]) -> list[CaptionReviewFlag]:
    return _select_review_candidates(segments, limit=_CAPTION_REVIEW_MAX_FLAGS)


def build_caption_quality_report(segments: Sequence[CaptionSegmentLike]) -> CaptionQualityReport:
    clean_segments = [
        segment
        for segment in segments
        if _clean_caption_text(segment.text) and not is_review_system_text(segment.text)
    ]
    probabilities = [segment.average_probability for segment in clean_segments if segment.average_probability is not None]
    average_probability = (sum(probabilities) / len(probabilities)) if probabilities else None
    all_flagged_segments = _select_review_candidates(clean_segments, limit=None)
    flagged_segments = all_flagged_segments[:_CAPTION_REVIEW_MAX_FLAGS]
    low_confidence_segment_count = _count_probable_low_confidence_flags(flagged_segments)
    return CaptionQualityReport(
        average_probability=average_probability,
        low_confidence_segment_count=low_confidence_segment_count,
        total_segment_count=len(clean_segments),
        flagged_segments=flagged_segments,
        review_recommended=bool(flagged_segments),
    )


def format_caption_review_document(report: CaptionQualityReport) -> str:
    lines = ["RADcast Caption Review", ""]
    if report.average_probability is not None:
        lines.append(f"Average word confidence: {report.average_probability:.0%}")
    lines.append(f"Flagged caption lines: {len(report.flagged_segments)}")
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
