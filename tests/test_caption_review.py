from __future__ import annotations

from radcast.services.caption_review import (
    CaptionQualityReport,
    CaptionReviewFlag,
    build_caption_export_quality_report,
    build_caption_quality_report,
    format_caption_review_document,
    is_review_system_text,
    select_review_candidates,
)
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
    assert report.low_confidence_segment_count == 1
    assert report.review_recommended is True
    assert [flag.reason for flag in report.flagged_segments] == [
        "probable duplication",
        "probable truncation",
        "probable low confidence",
    ]
    assert report.summary_text() == "Caption review suggested: 3 flagged segments."

    review_text = format_caption_review_document(report)

    assert "Flagged caption lines: 3" in review_text
    assert "probable duplication" in review_text
    assert "probable truncation" in review_text
    assert "probable low confidence" in review_text
    assert "confidence unknown" not in review_text
    assert "Welcome to the lecture" not in review_text


def test_caption_quality_report_summary_and_document_use_actual_flag_count():
    report = CaptionQualityReport(
        average_probability=0.82,
        low_confidence_segment_count=0,
        total_segment_count=1,
        flagged_segments=[
            CaptionReviewFlag(
                start=0.0,
                end=1.0,
                text="We need to",
                average_probability=0.92,
                reason="probable truncation",
            )
        ],
        review_recommended=True,
    )

    assert report.summary_text() == "Caption review suggested: 1 flagged segment."

    review_text = format_caption_review_document(report)

    assert "Flagged caption lines: 1" in review_text
    assert "probable truncation" in review_text


def test_build_caption_quality_report_counts_all_flags_but_caps_review_output_at_18():
    segments = [
        TranscriptSegmentTiming(
            text=f"Potentially low confidence line {index}",
            start=float(index),
            end=float(index) + 0.6,
            average_probability=0.39,
        )
        for index in range(20)
    ]

    report = build_caption_quality_report(segments)

    assert report.low_confidence_segment_count == 18
    assert len(report.flagged_segments) == 18
    assert len(select_review_candidates(segments)) == 18


def test_is_review_system_text_rejects_mixed_prompt_echo_line():
    assert is_review_system_text("Review low-confidence transcript lines carefully hello world") is True


def test_build_caption_export_quality_report_keeps_review_flags_with_export_metrics():
    review_report = CaptionQualityReport(
        average_probability=0.39,
        low_confidence_segment_count=1,
        total_segment_count=1,
        flagged_segments=[
            CaptionReviewFlag(
                start=0.0,
                end=1.4,
                text="This line should be checked",
                average_probability=0.39,
                reason="probable low confidence",
            )
        ],
        review_recommended=True,
    )
    export_report = CaptionQualityReport(
        average_probability=0.95,
        low_confidence_segment_count=0,
        total_segment_count=2,
        flagged_segments=[],
        review_recommended=False,
    )

    report = build_caption_export_quality_report(
        review_report=review_report,
        export_report=export_report,
    )

    assert report.review_recommended is True
    assert report.low_confidence_segment_count == 1
    assert report.total_segment_count == 2
    assert report.average_probability == 0.95
    assert report.flagged_segments == review_report.flagged_segments


def test_build_caption_export_quality_report_counts_only_low_confidence_flags():
    review_report = CaptionQualityReport(
        average_probability=0.92,
        low_confidence_segment_count=0,
        total_segment_count=1,
        flagged_segments=[],
        review_recommended=False,
    )
    export_flag = CaptionReviewFlag(
        start=0.0,
        end=1.0,
        text="We need to",
        average_probability=0.96,
        reason="probable truncation",
    )
    export_report = CaptionQualityReport(
        average_probability=0.95,
        low_confidence_segment_count=1,
        total_segment_count=2,
        flagged_segments=[export_flag],
        review_recommended=True,
    )

    report = build_caption_export_quality_report(
        review_report=review_report,
        export_report=export_report,
    )

    assert report.review_recommended is True
    assert report.low_confidence_segment_count == 0
    assert report.total_segment_count == 2
    assert report.average_probability == 0.95
    assert report.flagged_segments == [export_flag]
