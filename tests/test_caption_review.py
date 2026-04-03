from __future__ import annotations

from radcast.services.caption_review import build_caption_quality_report, format_caption_review_document, select_review_candidates
from radcast.services.speech_cleanup import TranscriptSegmentTiming


def test_select_review_candidates_flags_low_probability_duplication_and_truncation_with_explicit_reasons():
    segments = [
        TranscriptSegmentTiming(text="Welcome to the lecture", start=0.0, end=1.2, average_probability=0.94),
        TranscriptSegmentTiming(text="Thank you for coming today", start=1.3, end=2.2, average_probability=0.91),
        TranscriptSegmentTiming(text="Thank you for coming today", start=2.25, end=3.0, average_probability=0.92),
        TranscriptSegmentTiming(text="We need to", start=3.1, end=3.5, average_probability=0.88),
        TranscriptSegmentTiming(text="The next point is important", start=3.6, end=4.4, average_probability=0.39),
    ]

    flags = select_review_candidates(segments)

    assert [flag.text for flag in flags] == [
        "Thank you for coming today",
        "We need to",
        "The next point is important",
    ]
    assert [flag.reason for flag in flags] == [
        "probable duplication",
        "probable truncation",
        "probable low confidence",
    ]
    assert all("confidence unknown" not in flag.reason for flag in flags)


def test_build_caption_quality_report_and_document_include_only_flagged_segments():
    segments = [
        TranscriptSegmentTiming(text="Welcome to the lecture", start=0.0, end=1.2, average_probability=0.94),
        TranscriptSegmentTiming(text="Thank you for coming today", start=1.3, end=2.2, average_probability=0.91),
        TranscriptSegmentTiming(text="Thank you for coming today", start=2.25, end=3.0, average_probability=0.92),
        TranscriptSegmentTiming(text="We need to", start=3.1, end=3.5, average_probability=0.88),
        TranscriptSegmentTiming(text="The next point is important", start=3.6, end=4.4, average_probability=0.39),
    ]

    report = build_caption_quality_report(segments)

    assert report.total_segment_count == 5
    assert report.low_confidence_segment_count == 3
    assert report.review_recommended is True
    assert [flag.reason for flag in report.flagged_segments] == [
        "probable duplication",
        "probable truncation",
        "probable low confidence",
    ]

    review_text = format_caption_review_document(report)

    assert "probable duplication" in review_text
    assert "probable truncation" in review_text
    assert "probable low confidence" in review_text
    assert "confidence unknown" not in review_text
    assert "Welcome to the lecture" not in review_text

