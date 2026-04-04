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


def test_shape_lecture_caption_cues_filters_review_boilerplate_and_duplicate_outro_lines():
    segments = [
        TranscriptSegmentTiming(
            text="This is the final result of the review",
            start=0.0,
            end=1.0,
            average_probability=0.1,
        ),
        TranscriptSegmentTiming(
            text="In this lecture we derive the wave equation from first principles for the room.",
            start=1.0,
            end=6.0,
            average_probability=0.95,
        ),
        TranscriptSegmentTiming(
            text="Thank you for watching",
            start=6.0,
            end=7.0,
            average_probability=0.94,
        ),
        TranscriptSegmentTiming(
            text="Thank you for watching",
            start=7.02,
            end=8.0,
            average_probability=0.95,
        ),
        TranscriptSegmentTiming(
            text="Thank you for watching",
            start=8.02,
            end=9.0,
            average_probability=0.96,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)
    lowered = [cue.text.lower() for cue in shaped]

    assert all("final result of the review" not in text for text in lowered)
    assert lowered.count("thank you for watching") == 1
    assert " ".join(cue.text for cue in shaped) == (
        "In this lecture we derive the wave equation from first principles for the room. "
        "Thank you for watching"
    )


def test_shape_lecture_caption_cues_keeps_identical_spoken_lines_when_the_gap_is_large():
    segments = [
        TranscriptSegmentTiming(
            text="Thank you for watching",
            start=0.0,
            end=1.0,
            average_probability=0.94,
        ),
        TranscriptSegmentTiming(
            text="Thank you for watching",
            start=8.5,
            end=9.4,
            average_probability=0.95,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert [cue.text for cue in shaped] == ["Thank you for watching", "Thank you for watching"]
    assert [cue.start for cue in shaped] == [0.0, 8.5]
    assert [cue.end for cue in shaped] == [1.0, 9.4]


def test_shape_lecture_caption_cues_keeps_lecture_phrases_ordered_and_readable():
    segment = TranscriptSegmentTiming(
        text=(
            "First we define the operator in Hilbert space and then we apply it to the boundary term "
            "so the derivation stays in order for the students following along."
        ),
        start=0.0,
        end=16.0,
        average_probability=0.97,
    )

    shaped = shape_lecture_caption_cues([segment])

    assert " ".join(cue.text for cue in shaped) == segment.text
    assert len(shaped) >= 3
    assert max(len(cue.text) for cue in shaped) <= 84
    assert all(len(cue.text.split()) <= 14 for cue in shaped)
    assert all(cue.text.split()[-1].lower().rstrip(".,!?;:") not in {"and", "then", "the", "to"} for cue in shaped[:-1])
