from __future__ import annotations

from dataclasses import dataclass

import pytest

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


def test_shape_lecture_caption_cues_merges_duplicate_boundary_words_between_adjacent_cues():
    segments = [
        TranscriptSegmentTiming(
            text="Quantum mechanics relies",
            start=0.0,
            end=1.2,
            average_probability=0.96,
        ),
        TranscriptSegmentTiming(
            text="relies on the Schrödinger equation,",
            start=1.2,
            end=3.0,
            average_probability=0.96,
        ),
        TranscriptSegmentTiming(
            text="a mathematical tool used to determine",
            start=3.0,
            end=5.0,
            average_probability=0.95,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert [cue.text for cue in shaped] == [
        "Quantum mechanics relies on the Schrödinger equation,",
        "a mathematical tool used to determine",
    ]
    assert shaped[0].start == 0.0
    assert shaped[0].end == 3.0


def test_shape_lecture_caption_cues_merges_single_word_orphan_into_following_continuation():
    segments = [
        TranscriptSegmentTiming(
            text="When",
            start=10.0,
            end=10.2,
            average_probability=0.52,
        ),
        TranscriptSegmentTiming(
            text="When the Schrödinger equation is separable, we",
            start=10.2,
            end=12.5,
            average_probability=0.93,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert [cue.text for cue in shaped] == [
        "When the Schrödinger equation is separable, we",
    ]
    assert shaped[0].start == 10.0
    assert shaped[0].end == 12.5


def test_shape_lecture_caption_cues_merges_short_lead_in_with_following_phrase_when_readable():
    segments = [
        TranscriptSegmentTiming(
            text="Specifically,",
            start=0.0,
            end=0.3,
            average_probability=0.97,
        ),
        TranscriptSegmentTiming(
            text="here's quantum mechanics",
            start=0.3,
            end=2.0,
            average_probability=0.97,
        ),
        TranscriptSegmentTiming(
            text="in 60 seconds.",
            start=2.0,
            end=3.6,
            average_probability=0.96,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert [cue.text for cue in shaped] == [
        "Specifically, here's quantum mechanics in 60 seconds.",
    ]
    assert shaped[0].start == 0.0
    assert shaped[0].end == 3.6


def test_shape_lecture_caption_cues_does_not_merge_independent_short_adjacent_cues():
    segments = [
        TranscriptSegmentTiming(
            text="Hello world",
            start=0.0,
            end=1.25,
            average_probability=0.96,
        ),
        TranscriptSegmentTiming(
            text="Second line",
            start=1.4,
            end=1.95,
            average_probability=0.95,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert [cue.text for cue in shaped] == ["Hello world", "Second line"]
    assert [cue.start for cue in shaped] == [0.0, 1.4]
    assert [cue.end for cue in shaped] == [1.25, 1.95]


def test_shape_lecture_caption_cues_does_not_merge_new_sentence_that_starts_with_capitalized_weak_word():
    segments = [
        TranscriptSegmentTiming(
            text="Kia ora and welcome everyone",
            start=0.0,
            end=1.8,
            average_probability=0.84,
        ),
        TranscriptSegmentTiming(
            text="We will start with tikanga.",
            start=2.15,
            end=3.2,
            average_probability=0.88,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert [cue.text for cue in shaped] == [
        "Kia ora and welcome everyone",
        "We will start with tikanga.",
    ]


def test_shape_lecture_caption_cues_merges_duplicate_boundary_word_with_accent_variation():
    segments = [
        TranscriptSegmentTiming(
            text="Solving the Schrödinger",
            start=52.82,
            end=53.50,
            average_probability=0.95,
        ),
        TranscriptSegmentTiming(
            text="Schrodinger equation yields a basis set, comprising many different wave",
            start=53.50,
            end=57.08,
            average_probability=0.95,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert [cue.text for cue in shaped] == [
        "Solving the Schrödinger equation yields a basis set, comprising many different wave",
    ]


def test_shape_lecture_caption_cues_trims_duplicate_boundary_word_when_merge_would_be_too_long():
    segments = [
        TranscriptSegmentTiming(
            text="Wavefunctions are mathematical functions that encode the probability of measuring a particle",
            start=59.68,
            end=63.62,
            average_probability=0.97,
        ),
        TranscriptSegmentTiming(
            text="particle in a specific state.",
            start=63.62,
            end=64.98,
            average_probability=0.97,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert [cue.text for cue in shaped] == [
        "Wavefunctions are mathematical functions that encode",
        "the probability of measuring a particle in a specific state.",
    ]


def test_shape_lecture_caption_cues_merges_one_word_continuation_orphan_after_longer_cue():
    segments = [
        TranscriptSegmentTiming(
            text="The key to discovering entanglement lies in creating non -separable systems in real -world",
            start=155.08,
            end=160.14,
            average_probability=0.96,
        ),
        TranscriptSegmentTiming(
            text="scenarios.",
            start=160.14,
            end=160.82,
            average_probability=0.96,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert [cue.text for cue in shaped] == [
        "The key to discovering entanglement lies",
        "in creating non-separable systems in real-world scenarios.",
    ]


def test_shape_lecture_caption_cues_rechunks_long_one_word_fragment_run_into_phrase_chunks():
    segments = [
        TranscriptSegmentTiming(text="Don't", start=18.320, end=26.509, average_probability=0.98),
        TranscriptSegmentTiming(text="buy", start=26.509, end=34.698, average_probability=0.98),
        TranscriptSegmentTiming(text="cheap", start=34.698, end=42.888, average_probability=0.98),
        TranscriptSegmentTiming(text="bulbs", start=42.888, end=51.077, average_probability=0.98),
        TranscriptSegmentTiming(text="and", start=51.077, end=59.266, average_probability=0.98),
        TranscriptSegmentTiming(text="don't", start=59.266, end=67.455, average_probability=0.98),
        TranscriptSegmentTiming(text="screw", start=67.455, end=75.645, average_probability=0.98),
        TranscriptSegmentTiming(text="them", start=75.645, end=83.834, average_probability=0.98),
        TranscriptSegmentTiming(text="too", start=83.834, end=92.023, average_probability=0.98),
        TranscriptSegmentTiming(text="tight,", start=92.023, end=100.212, average_probability=0.98),
        TranscriptSegmentTiming(text="otherwise", start=100.212, end=108.402, average_probability=0.98),
        TranscriptSegmentTiming(text="they'll", start=108.402, end=116.591, average_probability=0.98),
        TranscriptSegmentTiming(text="break.", start=116.591, end=124.780, average_probability=0.98),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert [cue.text for cue in shaped] == [
        "Don't buy cheap bulbs",
        "and don't screw",
        "them too tight,",
        "otherwise they'll break.",
    ]
    assert [cue.start for cue in shaped] == pytest.approx([18.32, 51.077, 75.645, 100.212], abs=0.01)
    assert [cue.end for cue in shaped] == pytest.approx([51.077, 75.645, 100.212, 124.78], abs=0.01)


def test_shape_lecture_caption_cues_merges_medium_continuation_after_weak_boundary():
    segments = [
        TranscriptSegmentTiming(
            text="This equation accounts for a system's total energy, typically including the kinetic and",
            start=40.50,
            end=45.64,
            average_probability=0.91,
        ),
        TranscriptSegmentTiming(
            text="potential energy terms at a minimum.",
            start=45.64,
            end=47.24,
            average_probability=0.92,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert [cue.text for cue in shaped] == [
        "This equation accounts for a system's total",
        "energy, typically including the kinetic and potential energy terms at a minimum.",
    ]


def test_shape_lecture_caption_cues_merges_short_lowercase_continuation_after_nonterminal_boundary():
    segments = [
        TranscriptSegmentTiming(
            text="Wavefunctions are mathematical functions that encode the probability of measuring a particle",
            start=59.68,
            end=63.62,
            average_probability=0.97,
        ),
        TranscriptSegmentTiming(
            text="in a specific state.",
            start=63.62,
            end=64.98,
            average_probability=0.97,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert [cue.text for cue in shaped] == [
        "Wavefunctions are mathematical functions that encode",
        "the probability of measuring a particle in a specific state.",
    ]


def test_shape_lecture_caption_cues_trims_dangling_suffix_before_next_sentence_continuation():
    segments = [
        TranscriptSegmentTiming(
            text="single physical system, but entanglement is a phenomenon that occurs when multiple quantum",
            start=113.93,
            end=118.50,
            average_probability=0.98,
        ),
        TranscriptSegmentTiming(
            text="When dealing with the quantum state of multiple",
            start=118.98,
            end=123.791,
            average_probability=0.98,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert [cue.text for cue in shaped] == [
        "single physical system, but entanglement is a phenomenon that occurs when",
        "When dealing with the quantum state of multiple",
    ]


def test_shape_lecture_caption_cues_merges_short_non_sentence_fragment_into_following_continuation():
    segments = [
        TranscriptSegmentTiming(
            text="concept isn't just limited",
            start=235.50,
            end=238.584,
            average_probability=0.97,
        ),
        TranscriptSegmentTiming(
            text="to two boring electrons either.",
            start=238.584,
            end=242.440,
            average_probability=0.97,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert [cue.text for cue in shaped] == [
        "concept isn't just limited to two boring electrons either.",
    ]
    assert shaped[0].start == 235.50
    assert shaped[0].end == 242.440


def test_shape_lecture_caption_cues_shifts_preposition_boundary_into_following_continuation():
    segments = [
        TranscriptSegmentTiming(
            text="There will always be an inseparable term with dependence on",
            start=232.26,
            end=235.50,
            average_probability=0.97,
        ),
        TranscriptSegmentTiming(
            text="concept isn't just limited",
            start=235.50,
            end=238.584,
            average_probability=0.97,
        ),
        TranscriptSegmentTiming(
            text="to two boring electrons either.",
            start=238.584,
            end=242.440,
            average_probability=0.97,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert [cue.text for cue in shaped] == [
        "There will always be an inseparable term",
        "with dependence on concept isn't just limited to two boring electrons either.",
    ]
    assert shaped[0].start == 232.26
    assert shaped[0].end == shaped[1].start


def test_shape_lecture_caption_cues_merges_capitalized_proper_noun_continuation_after_weak_boundary():
    segments = [
        TranscriptSegmentTiming(
            text="any function that satisfies the",
            start=89.44,
            end=92.50,
            average_probability=0.99,
        ),
        TranscriptSegmentTiming(
            text="Schrödinger equation of our",
            start=92.50,
            end=95.08,
            average_probability=0.99,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert [cue.text for cue in shaped] == [
        "any function that satisfies the Schrödinger equation of our",
    ]


def test_shape_lecture_caption_cues_trims_long_duplicate_boundary_phrase_between_adjacent_cues():
    segments = [
        TranscriptSegmentTiming(
            text=(
                "equation for a single physical system, but entanglement "
                "is a phenomenon that occurs when"
            ),
            start=111.52,
            end=116.14,
            average_probability=0.98,
        ),
        TranscriptSegmentTiming(
            text="entanglement is a phenomenon that occurs when multiple quantum systems interact.",
            start=116.14,
            end=119.60,
            average_probability=0.98,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert [cue.text for cue in shaped] == [
        "equation for a single physical system, but entanglement is a phenomenon that occurs when",
        "multiple quantum systems interact.",
    ]


def test_shape_lecture_caption_cues_merges_short_trailing_continuation_after_weak_boundary():
    segments = [
        TranscriptSegmentTiming(
            text="as eigenstates and return the same function with a multiplier when plugged back into the",
            start=69.78,
            end=74.46,
            average_probability=0.97,
        ),
        TranscriptSegmentTiming(
            text="equation's left hand side.",
            start=74.46,
            end=75.62,
            average_probability=0.97,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert [cue.text for cue in shaped] == [
        "as eigenstates and return the same function",
        "with a multiplier when plugged back into the equation's left hand side.",
    ]


def test_shape_lecture_caption_cues_merges_two_word_continuation_after_when_boundary():
    segments = [
        TranscriptSegmentTiming(
            text="equation for a single physical system, but entanglement is a phenomenon that occurs when",
            start=113.744,
            end=116.140,
            average_probability=0.98,
        ),
        TranscriptSegmentTiming(
            text="multiple quantum",
            start=116.140,
            end=118.500,
            average_probability=0.98,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert [cue.text for cue in shaped] == [
        "equation for a single physical system, but entanglement is a phenomenon that occurs when multiple quantum",
    ]


def test_shape_lecture_caption_cues_trims_repeated_sentence_restart_at_next_boundary():
    segments = [
        TranscriptSegmentTiming(
            text="in quantum mechanics, let's go to entanglement.",
            start=108.1,
            end=110.7,
            average_probability=0.98,
        ),
        TranscriptSegmentTiming(
            text="Let's go to entanglement. I just explained that we can solve the Schrödinger",
            start=111.52,
            end=113.744,
            average_probability=0.98,
        ),
    ]

    shaped = shape_lecture_caption_cues(segments)

    assert [cue.text for cue in shaped] == [
        "in quantum mechanics, let's go to entanglement.",
        "I just explained that we can solve the Schrödinger",
    ]


def test_shape_lecture_caption_cues_normalizes_spaced_hyphens_within_words():
    segment = TranscriptSegmentTiming(
        text="and exhibit strange, non -intuitive phenomena.",
        start=12.0,
        end=14.2,
        average_probability=0.94,
    )

    shaped = shape_lecture_caption_cues([segment])

    assert [cue.text for cue in shaped] == ["and exhibit strange, non-intuitive phenomena."]
