from __future__ import annotations

from dataclasses import dataclass

from radcast.services.caption_cue_shaping import shape_lecture_caption_cues
from radcast.services.speech_cleanup import TranscriptSegmentTiming


@dataclass(frozen=True)
class ExtendedTranscriptSegmentTiming(TranscriptSegmentTiming):
    speaker_label: str = "Lecturer"


def test_shape_lecture_caption_cues_splits_long_lecture_span_into_multiple_readable_cues():
    segment = TranscriptSegmentTiming(
        text=(
            "Today we will look at how accessibility guidance changes the way we break lecture captions "
            "so viewers can keep up with the content without losing the meaning of the speaker's sentence."
        ),
        start=0.0,
        end=18.0,
        average_probability=0.91,
    )

    shaped = shape_lecture_caption_cues([segment])

    assert len(shaped) >= 3
    assert " ".join(cue.text for cue in shaped) == segment.text
    assert max(cue.end - cue.start for cue in shaped) < 13.0
    assert all(len(cue.text.split()) > 1 for cue in shaped)


def test_shape_lecture_caption_cues_preserves_cue_order_and_time_order():
    segments = [
        TranscriptSegmentTiming(
            text="We begin with the context for this lecture and why the examples matter.",
            start=0.0,
            end=7.2,
            average_probability=0.88,
        ),
        TranscriptSegmentTiming(
            text="Then we move into the details that students need to review later.",
            start=7.2,
            end=13.8,
            average_probability=0.9,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert " ".join(cue.text for cue in shaped) == " ".join(segment.text for segment in segments)
    assert [cue.start for cue in shaped] == sorted(cue.start for cue in shaped)
    assert [cue.end for cue in shaped] == sorted(cue.end for cue in shaped)
    assert shaped[0].start == 0.0
    assert shaped[-1].end == 13.8
    assert max(cue.end for cue in shaped if cue.start < 7.2) <= 7.2
    assert min(cue.start for cue in shaped if cue.end > 7.2) >= 7.2


def test_shape_lecture_caption_cues_keeps_phrase_boundaries_without_one_word_fragments_when_not_forced():
    segment = TranscriptSegmentTiming(
        text="This example should split into readable phrases instead of leaving a stranded word behind.",
        start=4.0,
        end=12.5,
        average_probability=0.86,
    )

    shaped = shape_lecture_caption_cues([segment])

    assert len(shaped) == 2
    assert [cue.text for cue in shaped] == [
        "This example should split into readable phrases",
        "instead of leaving a stranded word behind.",
    ]
    assert all(len(cue.text.split()) > 1 for cue in shaped)


def test_shape_lecture_caption_cues_returns_fresh_base_transcript_segment_timing_objects():
    segment = ExtendedTranscriptSegmentTiming(
        text=(
            "Today we need to be explicit that cue shaping returns fresh transcript timing objects "
            "instead of preserving subclass payload on split cues."
        ),
        start=0.0,
        end=12.0,
        average_probability=0.93,
        speaker_label="Professor",
    )

    shaped = shape_lecture_caption_cues([segment])

    assert shaped
    assert all(type(cue) is TranscriptSegmentTiming for cue in shaped)
    assert all(not hasattr(cue, "speaker_label") for cue in shaped)
