"""Accessibility-oriented cue shaping for lecture captions."""

from __future__ import annotations

import math
import re
import unicodedata
from typing import TYPE_CHECKING

from radcast.services.caption_review import _is_probable_duplication, is_review_system_text

if TYPE_CHECKING:
    from radcast.services.speech_cleanup import TranscriptSegmentTiming

_CAPTION_MAX_CUE_DURATION_SECONDS = 6.0
_CAPTION_MAX_CUE_CHARACTERS = 84
_CAPTION_MAX_CUE_WORDS = 14
_CAPTION_REPAIR_MAX_DURATION_SECONDS = 7.5
_CAPTION_REPAIR_MAX_CHARACTERS = 96
_CAPTION_REPAIR_MAX_WORDS = 16
_CAPTION_ORPHAN_MERGE_MAX_DURATION_SECONDS = 8.5
_CAPTION_ORPHAN_MERGE_MAX_CHARACTERS = 110
_CAPTION_ORPHAN_MERGE_MAX_WORDS = 18
_CAPTION_CONTINUATION_MERGE_MAX_DURATION_SECONDS = 8.5
_CAPTION_CONTINUATION_MERGE_MAX_CHARACTERS = 120
_CAPTION_CONTINUATION_MERGE_MAX_WORDS = 20
_TINY_CUE_MAX_WORDS = 3
_SPLIT_WEAK_TRAILING_WORDS = {"and", "or", "so", "than", "that", "the", "then", "to", "with"}
_REPAIR_WEAK_TRAILING_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "for",
    "from",
    "in",
    "into",
    "is",
    "of",
    "on",
    "or",
    "so",
    "than",
    "that",
    "the",
    "then",
    "to",
    "we",
    "when",
    "with",
}


def shape_lecture_caption_cues(segments: list[TranscriptSegmentTiming]) -> list[TranscriptSegmentTiming]:
    shaped: list[TranscriptSegmentTiming] = []
    previous_segment: TranscriptSegmentTiming | None = None
    for segment in segments:
        cleaned_text = _clean_caption_text(segment.text)
        if not cleaned_text:
            continue
        if is_review_system_text(cleaned_text):
            continue
        if previous_segment is not None and _is_probable_duplication(previous_segment, segment):
            previous_segment = segment
            continue
        words = cleaned_text.split()
        duration = max(0.2, float(segment.end) - float(segment.start))
        target_chunks = max(
            1,
            int(math.ceil(duration / _CAPTION_MAX_CUE_DURATION_SECONDS)),
            int(math.ceil(len(cleaned_text) / _CAPTION_MAX_CUE_CHARACTERS)),
            int(math.ceil(len(words) / _CAPTION_MAX_CUE_WORDS)),
        )
        if target_chunks <= 1:
            shaped.append(
                _build_transcript_segment_timing(
                    text=cleaned_text,
                    start=segment.start,
                    end=max(segment.end, segment.start + 0.2),
                    average_probability=segment.average_probability,
                )
            )
            previous_segment = segment
            continue

        token_groups = _split_caption_tokens_into_cues(words, target_chunks=target_chunks)
        consumed_tokens = 0
        total_tokens = max(1, len(words))
        for group_index, group in enumerate(token_groups):
            if not group:
                continue
            cue_text = " ".join(group).strip()
            cue_start = segment.start + (duration * (consumed_tokens / total_tokens))
            consumed_tokens += len(group)
            cue_end = segment.start + (duration * (consumed_tokens / total_tokens))
            if group_index == len(token_groups) - 1:
                cue_end = max(cue_end, segment.end)
            shaped.append(
                _build_transcript_segment_timing(
                    text=cue_text,
                    start=cue_start,
                    end=max(cue_end, cue_start + 0.2),
                    average_probability=segment.average_probability,
                )
            )
        if not shaped or shaped[-1].end < segment.end:
            shaped[-1] = _build_transcript_segment_timing(
                text=shaped[-1].text,
                start=shaped[-1].start,
                end=max(segment.end, shaped[-1].end),
                average_probability=shaped[-1].average_probability,
            )
        previous_segment = segment
    return _repair_shaped_caption_cues(shaped)


def _split_caption_tokens_into_cues(tokens: list[str], *, target_chunks: int) -> list[list[str]]:
    if not tokens:
        return []

    chunks: list[list[str]] = []
    start_index = 0
    total_tokens = len(tokens)
    for chunk_index in range(max(1, target_chunks)):
        remaining_tokens = total_tokens - start_index
        remaining_chunks = max(1, target_chunks - chunk_index)
        if remaining_tokens <= 0:
            break

        min_size = 1 if remaining_tokens <= remaining_chunks else 2
        target_size = max(min_size, int(math.ceil(remaining_tokens / remaining_chunks)))
        max_end = min(total_tokens, start_index + max(_CAPTION_MAX_CUE_WORDS, target_size + 2))
        best_end = None
        best_penalty = None
        for end_index in range(start_index + min_size, max_end + 1):
            tokens_left = total_tokens - end_index
            chunks_left = remaining_chunks - 1
            if chunks_left > 0 and tokens_left < chunks_left * 2:
                continue

            candidate_tokens = tokens[start_index:end_index]
            candidate_text = " ".join(candidate_tokens)
            if len(candidate_text) > _CAPTION_MAX_CUE_CHARACTERS and end_index > start_index + min_size:
                break

            penalty = abs(len(candidate_tokens) - target_size)
            trailing_word = candidate_tokens[-1].lower().rstrip(".,!?;:")
            if end_index < total_tokens and trailing_word in _SPLIT_WEAK_TRAILING_WORDS:
                penalty += 1.5
            if candidate_tokens[-1].endswith((".", "!", "?", ",", ";", ":")):
                penalty -= 0.6
            if best_penalty is None or penalty < best_penalty:
                best_end = end_index
                best_penalty = penalty

        if best_end is None:
            best_end = min(total_tokens, start_index + target_size)
        chunks.append(tokens[start_index:best_end])
        start_index = best_end

    if start_index < total_tokens:
        remainder = tokens[start_index:]
        if chunks and len(remainder) == 1 and len(chunks[-1]) > 2:
            trailing_word = chunks[-1].pop()
            chunks.append([trailing_word, remainder[0]])
        elif chunks:
            chunks[-1].extend(remainder)
        else:
            chunks.append(remainder)

    return [chunk for chunk in chunks if chunk]


def _clean_caption_text(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    return re.sub(r"(?<=\w)\s*-\s*(?=\w)", "-", cleaned)


def _repair_shaped_caption_cues(segments: list[TranscriptSegmentTiming]) -> list[TranscriptSegmentTiming]:
    repaired: list[TranscriptSegmentTiming] = []
    for segment in segments:
        candidate = _build_transcript_segment_timing(
            text=_clean_caption_text(segment.text),
            start=segment.start,
            end=segment.end,
            average_probability=segment.average_probability,
        )
        if not candidate.text:
            continue
        while repaired:
            merged = _maybe_merge_adjacent_cues(repaired[-1], candidate)
            if merged is not None:
                repaired.pop()
                candidate = merged
                continue
            trimmed_previous = _maybe_trim_previous_dangling_suffix(repaired[-1], candidate)
            if trimmed_previous is not None:
                repaired[-1] = trimmed_previous
                continue
            trimmed = _maybe_trim_adjacent_duplicate_boundary(repaired[-1], candidate)
            if trimmed is None:
                break
            candidate = trimmed
        repaired.append(candidate)
    repaired = _repair_preposition_boundary_bridges(repaired)
    return _repair_fragmented_caption_runs(repaired)


def _repair_fragmented_caption_runs(
    segments: list[TranscriptSegmentTiming],
) -> list[TranscriptSegmentTiming]:
    if len(segments) < 2:
        return segments

    repaired: list[TranscriptSegmentTiming] = []
    index = 0
    while index < len(segments):
        fragment_run = _collect_fragmented_caption_run(segments, index)
        if fragment_run is None:
            repaired.append(segments[index])
            index += 1
            continue

        run_segments, next_index = fragment_run
        repaired.extend(_rechunk_fragment_run(run_segments))
        index = next_index

    return repaired


def _collect_fragmented_caption_run(
    segments: list[TranscriptSegmentTiming],
    start_index: int,
) -> tuple[list[TranscriptSegmentTiming], int] | None:
    first = segments[start_index]
    first_text = _clean_caption_text(first.text)
    if not first_text:
        return None

    first_words = first_text.split()
    if len(first_words) > 3:
        return None

    run: list[TranscriptSegmentTiming] = [first]
    total_words = len(first_words)
    total_duration = max(0.2, float(first.end) - float(first.start))
    index = start_index + 1
    while index < len(segments):
        candidate = segments[index]
        candidate_text = _clean_caption_text(candidate.text)
        if not candidate_text:
            break

        candidate_words = candidate_text.split()
        if len(candidate_words) > 3:
            break
        if float(candidate.start) - float(run[-1].end) > 0.6:
            break

        run.append(candidate)
        total_words += len(candidate_words)
        total_duration = max(0.2, float(candidate.end) - float(run[0].start))
        index += 1

    if len(run) < 4:
        return None
    if total_words < 6 or total_duration < 8.0:
        return None
    if sum(len(_clean_caption_text(segment.text).split()) for segment in run) < 6:
        return None

    return run, index


def _rechunk_fragment_run(
    run: list[TranscriptSegmentTiming],
) -> list[TranscriptSegmentTiming]:
    if not run:
        return []

    combined_tokens: list[str] = []
    for segment in run:
        combined_tokens.extend(_clean_caption_text(segment.text).split())
    if not combined_tokens:
        return []

    combined_start = float(run[0].start)
    combined_end = float(run[-1].end)
    combined_duration = max(0.2, combined_end - combined_start)
    target_chunks = max(1, math.ceil(len(combined_tokens) / 4))
    grouped_tokens = _split_caption_tokens_into_cues(combined_tokens, target_chunks=target_chunks)
    if not grouped_tokens:
        return []

    weighted_probability = _merge_run_average_probability(run)
    total_tokens = max(1, len(combined_tokens))
    consumed_tokens = 0
    rechunked: list[TranscriptSegmentTiming] = []
    for group_index, group in enumerate(grouped_tokens):
        if not group:
            continue
        cue_start = combined_start + (combined_duration * (consumed_tokens / total_tokens))
        consumed_tokens += len(group)
        cue_end = combined_start + (combined_duration * (consumed_tokens / total_tokens))
        if group_index == len(grouped_tokens) - 1:
            cue_end = max(cue_end, combined_end)
        rechunked.append(
            _build_transcript_segment_timing(
                text=" ".join(group).strip(),
                start=cue_start,
                end=max(cue_end, cue_start + 0.2),
                average_probability=weighted_probability,
            )
        )
    return rechunked


def _merge_run_average_probability(run: list[TranscriptSegmentTiming]) -> float | None:
    weighted_total = 0.0
    weight = 0.0
    for segment in run:
        if segment.average_probability is None:
            continue
        duration = max(0.2, float(segment.end) - float(segment.start))
        weighted_total += float(segment.average_probability) * duration
        weight += duration
    if weight <= 0.0:
        return run[0].average_probability if run else None
    return weighted_total / weight


def _repair_preposition_boundary_bridges(
    segments: list[TranscriptSegmentTiming],
) -> list[TranscriptSegmentTiming]:
    if len(segments) < 2:
        return segments

    bridged: list[TranscriptSegmentTiming] = []
    index = 0
    while index < len(segments):
        current = segments[index]
        next_segment = segments[index + 1] if index + 1 < len(segments) else None
        if next_segment is None:
            bridged.append(current)
            break

        current_text = _clean_caption_text(current.text)
        next_text = _clean_caption_text(next_segment.text)
        if (
            current_text
            and next_text
            and _ends_with_preposition_boundary(current_text)
            and (_starts_with_continuation(next_text) or _starts_clause_restart(next_text))
        ):
            shifted = _maybe_shift_trailing_suffix_into_next_cue(current, next_segment)
            if shifted is not None:
                bridged.extend(shifted)
                index += 2
                continue

        bridged.append(current)
        index += 1

    return bridged


def _maybe_merge_adjacent_cues(
    first: TranscriptSegmentTiming,
    second: TranscriptSegmentTiming,
) -> TranscriptSegmentTiming | None:
    first_text = _clean_caption_text(first.text)
    second_text = _clean_caption_text(second.text)
    if not first_text or not second_text:
        return None

    gap_seconds = max(0.0, float(second.start) - float(first.end))
    if gap_seconds > 0.35:
        return None

    first_tokens = first_text.split()
    second_tokens = second_text.split()
    overlap_count = _boundary_overlap_token_count(first_tokens, second_tokens)
    combined_tokens = [*first_tokens, *second_tokens[overlap_count:]]
    combined_text = " ".join(combined_tokens).strip()
    if not combined_text:
        return None

    second_tiny = len(second_tokens) <= _TINY_CUE_MAX_WORDS
    second_continuation = _starts_with_continuation(second_text)
    orphan_merge = second_continuation and len(second_tokens) == 1
    first_weak = _ends_with_weak_boundary(first_text)
    if _ends_with_preposition_boundary(first_text) and _starts_clause_restart(second_text):
        return None
    weak_boundary_merge = first_weak and len(second_tokens) <= 7 and not _ends_sentence(first_text)
    continuation_merge = (second_continuation and first_weak and len(second_tokens) <= 7)
    short_nonterminal_continuation = (
        not _ends_clause_boundary(first_text)
        and second_continuation
        and len(second_tokens) <= 4
    )
    short_fragment_merge = (
        len(first_tokens) <= 4
        and not _ends_sentence(first_text)
        and second_continuation
        and len(second_tokens) <= 6
    )
    combined_duration = max(0.2, float(second.end) - float(first.start))
    max_duration = _CAPTION_REPAIR_MAX_DURATION_SECONDS
    max_characters = _CAPTION_REPAIR_MAX_CHARACTERS
    max_words = _CAPTION_REPAIR_MAX_WORDS
    if orphan_merge:
        max_duration = _CAPTION_ORPHAN_MERGE_MAX_DURATION_SECONDS
        max_characters = _CAPTION_ORPHAN_MERGE_MAX_CHARACTERS
        max_words = _CAPTION_ORPHAN_MERGE_MAX_WORDS
    elif continuation_merge or weak_boundary_merge:
        max_duration = _CAPTION_CONTINUATION_MERGE_MAX_DURATION_SECONDS
        max_characters = _CAPTION_CONTINUATION_MERGE_MAX_CHARACTERS
        max_words = _CAPTION_CONTINUATION_MERGE_MAX_WORDS
    if (
        combined_duration > max_duration
        or len(combined_text) > max_characters
        or len(combined_tokens) > max_words
    ):
        return None

    first_tiny = len(first_tokens) <= _TINY_CUE_MAX_WORDS
    overlap_merge = overlap_count > 0 and not _ends_clause_boundary(first_text)

    should_merge = (
        overlap_merge
        or (second_continuation and first_tiny)
        or orphan_merge
        or continuation_merge
        or weak_boundary_merge
        or short_nonterminal_continuation
        or short_fragment_merge
    )
    if not should_merge:
        return None

    return _build_transcript_segment_timing(
        text=combined_text,
        start=first.start,
        end=max(first.end, second.end),
        average_probability=_merge_average_probability(first, second),
    )


def _maybe_shift_trailing_suffix_into_next_cue(
    first: TranscriptSegmentTiming,
    second: TranscriptSegmentTiming,
) -> tuple[TranscriptSegmentTiming, TranscriptSegmentTiming] | None:
    first_text = _clean_caption_text(first.text)
    second_text = _clean_caption_text(second.text)
    if not first_text or not second_text:
        return None
    if not _ends_with_preposition_boundary(first_text):
        return None
    if not (_starts_with_continuation(second_text) or _starts_clause_restart(second_text)):
        return None

    gap_seconds = max(0.0, float(second.start) - float(first.end))
    if gap_seconds > 0.35:
        return None

    first_tokens = first_text.split()
    second_tokens = second_text.split()
    if len(first_tokens) < 5 or len(second_tokens) < 2:
        return None

    combined_duration = max(0.2, float(second.end) - float(first.start))
    max_trim = min(3, len(first_tokens) - 3)
    for trim_count in range(max_trim, 0, -1):
        left_tokens = first_tokens[:-trim_count]
        suffix_tokens = first_tokens[-trim_count:]
        if len(left_tokens) < 3:
            continue

        left_text = " ".join(left_tokens).strip()
        if not left_text:
            continue
        if _ends_with_preposition_boundary(left_text) or _ends_with_weak_boundary(left_text):
            continue

        right_tokens = [*suffix_tokens, *second_tokens]
        right_text = " ".join(right_tokens).strip()
        if not right_text:
            continue

        left_ratio = len(left_tokens) / max(1, len(first_tokens))
        left_duration = max(0.2, combined_duration * left_ratio)
        right_duration = max(0.2, combined_duration - left_duration)
        if right_duration > _CAPTION_CONTINUATION_MERGE_MAX_DURATION_SECONDS:
            continue
        if len(left_text) > _CAPTION_REPAIR_MAX_CHARACTERS or len(right_text) > _CAPTION_CONTINUATION_MERGE_MAX_CHARACTERS:
            continue
        if len(left_tokens) > _CAPTION_MAX_CUE_WORDS or len(right_tokens) > _CAPTION_CONTINUATION_MERGE_MAX_WORDS:
            continue

        left_average_probability = first.average_probability
        right_average_probability = _merge_average_probability(first, second)
        left_segment = _build_transcript_segment_timing(
            text=left_text,
            start=first.start,
            end=max(first.start + 0.2, first.start + left_duration),
            average_probability=left_average_probability,
        )
        right_segment = _build_transcript_segment_timing(
            text=right_text,
            start=max(left_segment.end, second.start),
            end=max(second.end, max(left_segment.end, second.start) + right_duration),
            average_probability=right_average_probability,
        )
        return left_segment, right_segment

    return None


def _boundary_overlap_token_count(first_tokens: list[str], second_tokens: list[str]) -> int:
    max_overlap = min(8, len(first_tokens), len(second_tokens))
    for size in range(max_overlap, 0, -1):
        first_suffix = [_normalized_boundary_token(token) for token in first_tokens[-size:]]
        second_prefix = [_normalized_boundary_token(token) for token in second_tokens[:size]]
        if first_suffix == second_prefix and all(first_suffix):
            return size
    return 0


def _normalized_boundary_token(token: str) -> str:
    normalized = unicodedata.normalize("NFKD", token)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.strip(" \t\r\n\"'“”‘’«»()[]{}.,!?;:-").lower()


def _maybe_trim_previous_dangling_suffix(
    first: TranscriptSegmentTiming,
    second: TranscriptSegmentTiming,
) -> TranscriptSegmentTiming | None:
    first_text = _clean_caption_text(first.text)
    second_text = _clean_caption_text(second.text)
    if not first_text or not second_text:
        return None

    gap_seconds = max(0.0, float(second.start) - float(first.end))
    if gap_seconds > 0.9:
        return None
    if _ends_sentence(first_text) or not _starts_sentence_like(second_text):
        return None

    first_tokens = first_text.split()
    second_tokens = second_text.split()
    if len(first_tokens) < 3 or len(second_tokens) < 3:
        return None

    second_normalized = {tok for tok in (_normalized_boundary_token(token) for token in second_tokens) if tok}
    for trim_count in range(min(3, len(first_tokens) - 1), 1, -1):
        suffix = [_normalized_boundary_token(token) for token in first_tokens[-trim_count:]]
        if not all(suffix) or not all(token in second_normalized for token in suffix):
            continue
        trimmed_tokens = first_tokens[:-trim_count]
        if len(trimmed_tokens) < 3:
            continue
        trimmed_text = " ".join(trimmed_tokens).strip()
        if not trimmed_text:
            continue
        if not (_ends_with_weak_boundary(trimmed_text) or _ends_clause_boundary(trimmed_text)):
            continue
        return _build_transcript_segment_timing(
            text=trimmed_text,
            start=first.start,
            end=first.end,
            average_probability=first.average_probability,
        )
    return None


def _maybe_trim_adjacent_duplicate_boundary(
    first: TranscriptSegmentTiming,
    second: TranscriptSegmentTiming,
) -> TranscriptSegmentTiming | None:
    first_text = _clean_caption_text(first.text)
    second_text = _clean_caption_text(second.text)
    if not first_text or not second_text:
        return None

    gap_seconds = max(0.0, float(second.start) - float(first.end))
    first_tokens = first_text.split()
    second_tokens = second_text.split()
    overlap_count = _boundary_overlap_token_count(first_tokens, second_tokens)
    max_gap_seconds = 0.35
    if overlap_count >= 3:
        max_gap_seconds = 1.2
    if gap_seconds > max_gap_seconds:
        return None
    if overlap_count <= 0 or overlap_count >= len(second_tokens):
        return None

    trimmed_text = " ".join(second_tokens[overlap_count:]).strip()
    if not trimmed_text:
        return None

    return _build_transcript_segment_timing(
        text=trimmed_text,
        start=second.start,
        end=second.end,
        average_probability=second.average_probability,
    )


def _ends_with_weak_boundary(text: str) -> bool:
    tokens = text.split()
    if not tokens:
        return False
    return _normalized_boundary_token(tokens[-1]) in _REPAIR_WEAK_TRAILING_WORDS


def _ends_with_preposition_boundary(text: str) -> bool:
    tokens = text.split()
    if not tokens:
        return False
    return _normalized_boundary_token(tokens[-1]) in {"at", "by", "for", "from", "in", "of", "on", "to", "with"}


def _starts_with_continuation(text: str) -> bool:
    tokens = text.split()
    if not tokens:
        return False
    first = tokens[0]
    normalized = _normalized_boundary_token(first)
    stripped = first.lstrip("\"'“”‘’«»([{")
    if normalized in _REPAIR_WEAK_TRAILING_WORDS and stripped and stripped[0].islower():
        return True
    return bool(stripped) and stripped[0].islower()


def _starts_clause_restart(text: str) -> bool:
    tokens = text.split()
    if len(tokens) < 2:
        return False
    first = _normalized_boundary_token(tokens[0])
    second = _normalized_boundary_token(tokens[1])
    if not first or not second:
        return False
    return second in {
        "am",
        "are",
        "aren't",
        "arent",
        "is",
        "isn't",
        "isnt",
        "was",
        "wasn't",
        "wasnt",
        "were",
        "weren't",
        "werent",
        "has",
        "have",
        "had",
    }


def _starts_sentence_like(text: str) -> bool:
    tokens = text.split()
    if not tokens:
        return False
    first = tokens[0].lstrip("\"'“”‘’«»([{")
    return bool(first) and first[0].isupper() and not _starts_with_continuation(text)


def _ends_sentence(text: str) -> bool:
    stripped = text.rstrip()
    return stripped.endswith((".", "!", "?", "»", "”"))


def _ends_clause_boundary(text: str) -> bool:
    stripped = text.rstrip()
    return stripped.endswith((".", "!", "?", ",", ";", ":", "»", "”"))


def _merge_average_probability(
    first: TranscriptSegmentTiming,
    second: TranscriptSegmentTiming,
) -> float | None:
    weighted_total = 0.0
    weight = 0.0
    for segment in (first, second):
        if segment.average_probability is None:
            continue
        duration = max(0.2, float(segment.end) - float(segment.start))
        weighted_total += float(segment.average_probability) * duration
        weight += duration
    if weight <= 0.0:
        return first.average_probability if first.average_probability is not None else second.average_probability
    return weighted_total / weight


def _build_transcript_segment_timing(
    *,
    text: str,
    start: float,
    end: float,
    average_probability: float | None,
) -> TranscriptSegmentTiming:
    from radcast.services.speech_cleanup import TranscriptSegmentTiming

    return TranscriptSegmentTiming(
        text=text,
        start=start,
        end=end,
        average_probability=average_probability,
    )
