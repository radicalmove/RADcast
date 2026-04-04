"""Accessibility-oriented cue shaping for lecture captions."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from radcast.services.caption_review import _is_probable_duplication, is_review_system_text

if TYPE_CHECKING:
    from radcast.services.speech_cleanup import TranscriptSegmentTiming

_CAPTION_MAX_CUE_DURATION_SECONDS = 6.0
_CAPTION_MAX_CUE_CHARACTERS = 84
_CAPTION_MAX_CUE_WORDS = 14
_WEAK_TRAILING_WORDS = {"and", "or", "so", "than", "that", "the", "then", "to", "with"}


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
    return shaped


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
            if end_index < total_tokens and trailing_word in _WEAK_TRAILING_WORDS:
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
    return " ".join(str(text or "").split()).strip()


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
