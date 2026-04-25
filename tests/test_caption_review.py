from __future__ import annotations

from radcast.services.caption_review import (
    CaptionQualityReport,
    CaptionReviewFlag,
    assess_caption_accessibility,
    build_caption_export_quality_report,
    build_caption_quality_report,
    build_selective_rerun_plan,
    format_caption_review_document,
    is_review_system_text,
    sanitize_review_candidate_text,
    select_review_candidates,
    should_accept_sparse_review_candidate,
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


def test_build_caption_quality_report_flags_probable_critical_term_miss():
    segments = [
        TranscriptSegmentTiming(
            text="Aitikanga Māori space",
            start=0.0,
            end=1.2,
            average_probability=0.95,
        )
    ]

    report = build_caption_quality_report(segments, critical_terms=["tikanga"])
    assessment = assess_caption_accessibility(report)

    assert report.review_recommended is True
    assert [flag.reason for flag in report.flagged_segments] == ["probable critical term miss: tikanga"]
    assert assessment.status.name.lower() == "failed"


def test_build_caption_quality_report_flags_probable_glossary_term_substitution():
    segments = [
        TranscriptSegmentTiming(
            text="transcription against tikanga",
            start=0.0,
            end=1.2,
            average_probability=0.95,
        )
    ]

    report = build_caption_quality_report(segments, critical_terms=["transgression"])
    assessment = assess_caption_accessibility(report)

    assert report.review_recommended is True
    assert [flag.reason for flag in report.flagged_segments] == ["probable critical term miss: transgression"]
    assert assessment.status.name.lower() == "failed"


def test_build_caption_quality_report_flags_probable_manaaki_term_miss():
    segments = [
        TranscriptSegmentTiming(
            text="monarchy those visitors",
            start=0.0,
            end=1.2,
            average_probability=0.95,
        )
    ]

    report = build_caption_quality_report(segments, critical_terms=["manaaki"])
    assessment = assess_caption_accessibility(report)

    assert report.review_recommended is True
    assert [flag.reason for flag in report.flagged_segments] == ["probable critical term miss: manaaki"]
    assert assessment.status.name.lower() == "failed"


def test_build_caption_quality_report_does_not_flag_short_glossary_terms_on_unrelated_short_words():
    segments = [
        TranscriptSegmentTiming(
            text="Hi!",
            start=0.0,
            end=14.5,
            average_probability=0.91,
        ),
        TranscriptSegmentTiming(
            text="Have to make sure",
            start=14.5,
            end=19.227,
            average_probability=0.92,
        ),
    ]

    report = build_caption_quality_report(segments, critical_terms=["hui", "rangatahi"])

    assert all(
        not flag.reason.startswith("probable critical term miss:")
        for flag in report.flagged_segments
    )


def test_build_caption_quality_report_flags_sparse_lightbulb_style_runs_for_rerun():
    segments = [
        TranscriptSegmentTiming(
            text="Hi!",
            start=0.0,
            end=14.5,
            average_probability=0.91,
        ),
        TranscriptSegmentTiming(
            text="Have to make sure",
            start=14.5,
            end=19.227,
            average_probability=0.92,
        ),
        TranscriptSegmentTiming(
            text="that the bulb is not too hot.",
            start=19.227,
            end=27.5,
            average_probability=0.93,
        ),
        TranscriptSegmentTiming(
            text="Okay, it's time",
            start=66.5,
            end=78.688,
            average_probability=0.95,
        ),
        TranscriptSegmentTiming(
            text="to select a proper lightbulb.",
            start=78.688,
            end=99.0,
            average_probability=0.95,
        ),
        TranscriptSegmentTiming(
            text="Always make sure",
            start=99.0,
            end=111.188,
            average_probability=0.95,
        ),
        TranscriptSegmentTiming(
            text="that the power rating of",
            start=111.188,
            end=131.5,
            average_probability=0.95,
        ),
        TranscriptSegmentTiming(
            text="It's already out, so always use a",
            start=131.5,
            end=137.14,
            average_probability=0.95,
        ),
        TranscriptSegmentTiming(
            text="tool to get this screw part out.",
            start=137.14,
            end=142.78,
            average_probability=0.95,
        ),
    ]

    report = build_caption_quality_report(segments)

    assert any(flag.reason == "probable sparse caption run" for flag in report.flagged_segments)


def test_build_caption_quality_report_flags_sparse_caption_gaps_for_rerun():
    segments = [
        TranscriptSegmentTiming(
            text="Hi!",
            start=0.0,
            end=14.5,
            average_probability=0.91,
        ),
        TranscriptSegmentTiming(
            text="Have to make sure",
            start=14.5,
            end=19.227,
            average_probability=0.92,
        ),
        TranscriptSegmentTiming(
            text="that the bulb is not too hot.",
            start=19.227,
            end=27.5,
            average_probability=0.93,
        ),
        TranscriptSegmentTiming(
            text="They have temperature cycles and screw",
            start=27.5,
            end=32.088,
            average_probability=0.95,
        ),
        TranscriptSegmentTiming(
            text="part is rusted, when you try",
            start=32.088,
            end=36.676,
            average_probability=0.95,
        ),
        TranscriptSegmentTiming(
            text="to unscrew it from the",
            start=36.676,
            end=40.5,
            average_probability=0.95,
        ),
        TranscriptSegmentTiming(
            text="Okay, it's time",
            start=66.5,
            end=78.688,
            average_probability=0.95,
        ),
        TranscriptSegmentTiming(
            text="to select a proper lightbulb.",
            start=78.688,
            end=99.0,
            average_probability=0.95,
        ),
    ]

    report = build_caption_quality_report(segments)
    plan = build_selective_rerun_plan(report)

    assert any(flag.reason == "probable sparse caption gap" for flag in report.flagged_segments)
    assert any(
        any(flag.reason == "probable sparse caption gap" for flag in window.flags)
        for window in plan
    )


def test_build_selective_rerun_plan_keeps_sparse_gaps_separate_from_sparse_runs():
    segments = [
        TranscriptSegmentTiming(
            text="Hi!",
            start=0.0,
            end=14.5,
            average_probability=0.91,
        ),
        TranscriptSegmentTiming(
            text="Have to make sure",
            start=14.5,
            end=19.227,
            average_probability=0.92,
        ),
        TranscriptSegmentTiming(
            text="that the bulb is not too hot.",
            start=19.227,
            end=27.5,
            average_probability=0.93,
        ),
        TranscriptSegmentTiming(
            text="They have temperature cycles and screw",
            start=27.5,
            end=32.088,
            average_probability=0.95,
        ),
        TranscriptSegmentTiming(
            text="part is rusted, when you try",
            start=32.088,
            end=36.676,
            average_probability=0.95,
        ),
        TranscriptSegmentTiming(
            text="to unscrew it from the",
            start=36.676,
            end=40.5,
            average_probability=0.95,
        ),
        TranscriptSegmentTiming(
            text="Okay, it's time",
            start=66.5,
            end=78.688,
            average_probability=0.95,
        ),
        TranscriptSegmentTiming(
            text="to select a proper lightbulb.",
            start=78.688,
            end=99.0,
            average_probability=0.95,
        ),
        TranscriptSegmentTiming(
            text="Always make sure",
            start=99.0,
            end=111.188,
            average_probability=0.95,
        ),
        TranscriptSegmentTiming(
            text="that the power rating of",
            start=111.188,
            end=131.5,
            average_probability=0.95,
        ),
    ]

    report = build_caption_quality_report(segments)
    plan = build_selective_rerun_plan(report)

    mixed_window_reasons = [
        {flag.reason for flag in window.flags}
        for window in plan
        if any(flag.reason == "probable sparse caption gap" for flag in window.flags)
    ]

    assert mixed_window_reasons
    assert all("probable sparse caption run" not in reasons for reasons in mixed_window_reasons)


def test_build_selective_rerun_plan_merges_adjacent_flags_and_prioritizes_critical_terms():
    report = CaptionQualityReport(
        average_probability=0.71,
        low_confidence_segment_count=1,
        total_segment_count=3,
        flagged_segments=[
            CaptionReviewFlag(
                start=0.0,
                end=1.0,
                text="Aitikanga Māori space",
                average_probability=0.93,
                reason="probable critical term miss: tikanga",
            ),
            CaptionReviewFlag(
                start=1.02,
                end=1.8,
                text="This line is low confidence",
                average_probability=0.39,
                reason="probable low confidence",
            ),
        ],
        review_recommended=True,
    )

    plan = build_selective_rerun_plan(report)

    assert len(plan) == 1
    assert plan[0].start == 0.0
    assert plan[0].end >= 1.8
    assert plan[0].priority_reason == "probable critical term miss: tikanga"
    assert [flag.reason for flag in plan[0].flags] == [
        "probable critical term miss: tikanga",
        "probable low confidence",
    ]


def test_build_caption_quality_report_flags_sparse_caption_runs_for_rerun():
    segments = [
        TranscriptSegmentTiming(
            text="Don't buy cheap bulbs",
            start=18.320,
            end=51.077,
            average_probability=0.98,
        ),
        TranscriptSegmentTiming(
            text="and don't screw",
            start=51.077,
            end=75.645,
            average_probability=0.98,
        ),
        TranscriptSegmentTiming(
            text="them too tight,",
            start=75.645,
            end=100.212,
            average_probability=0.98,
        ),
        TranscriptSegmentTiming(
            text="otherwise they'll break.",
            start=100.212,
            end=124.780,
            average_probability=0.98,
        ),
    ]

    report = build_caption_quality_report(segments)
    plan = build_selective_rerun_plan(report)

    assert [flag.reason for flag in report.flagged_segments] == ["probable sparse caption run"]
    assert len(plan) == 1
    assert plan[0].start == 18.32
    assert plan[0].end == 124.78
    assert plan[0].priority_reason == "probable sparse caption run"


def test_sparse_review_candidate_acceptance_prefers_materially_denser_replacement():
    current_segment = TranscriptSegmentTiming(
        text="Don't buy cheap bulbs",
        start=18.32,
        end=51.077,
        average_probability=0.98,
    )
    candidate_segment = TranscriptSegmentTiming(
        text="Don't buy cheap bulbs unless you also want to replace them again tomorrow",
        start=18.32,
        end=51.077,
        average_probability=0.985,
    )
    similar_probability_sparse_candidate = TranscriptSegmentTiming(
        text="Don't buy cheap bulbs",
        start=18.32,
        end=51.077,
        average_probability=0.989,
    )

    assert should_accept_sparse_review_candidate(
        current_segment=current_segment,
        candidate_segment=candidate_segment,
    ) is True
    assert should_accept_sparse_review_candidate(
        current_segment=current_segment,
        candidate_segment=similar_probability_sparse_candidate,
    ) is False


def test_targeted_review_selects_only_high_risk_truncations_and_low_confidence_segments():
    segments = [
        TranscriptSegmentTiming(
            text="This equation accounts for a system's total energy, typically including the kinetic and",
            start=0.0,
            end=2.0,
            average_probability=0.91,
        ),
        TranscriptSegmentTiming(
            text="Wave functions are mathematical functions that encode the probability of measuring a",
            start=2.1,
            end=4.0,
            average_probability=0.99,
        ),
        TranscriptSegmentTiming(
            text="I just explained that we can solve the Schrödinger equation for a single physical system, but",
            start=4.1,
            end=6.0,
            average_probability=0.98,
        ),
        TranscriptSegmentTiming(
            text="When",
            start=6.1,
            end=6.3,
            average_probability=0.52,
        ),
        TranscriptSegmentTiming(
            text="There will always be an inseparable term with dependence on",
            start=6.4,
            end=8.0,
            average_probability=0.97,
        ),
        TranscriptSegmentTiming(
            text="That's because the system is entangled and the state of",
            start=8.1,
            end=9.5,
            average_probability=0.93,
        ),
        TranscriptSegmentTiming(
            text="This line is genuinely low confidence",
            start=9.6,
            end=10.6,
            average_probability=0.32,
        ),
    ]

    flags = select_review_candidates(segments, strategy_id="targeted_review")

    assert [flag.text for flag in flags] == [
        "I just explained that we can solve the Schrödinger equation for a single physical system, but",
        "When",
        "There will always be an inseparable term with dependence on",
        "That's because the system is entangled and the state of",
        "This line is genuinely low confidence",
    ]
    assert [flag.reason for flag in flags] == [
        "probable truncation",
        "probable truncation",
        "probable truncation",
        "probable truncation",
        "probable low confidence",
    ]


def test_targeted_review_skips_preposition_truncation_when_the_next_caption_continues_the_sentence():
    segments = [
        TranscriptSegmentTiming(
            text="There will always be an inseparable term with dependence on",
            start=232.26,
            end=235.50,
            average_probability=0.97,
        ),
        TranscriptSegmentTiming(
            text="concept isn't just limited to two boring electrons either.",
            start=235.50,
            end=242.440,
            average_probability=0.97,
        ),
    ]

    flags = select_review_candidates(segments, strategy_id="targeted_review")

    assert flags == []


def test_is_review_system_text_rejects_mixed_prompt_echo_line():
    assert is_review_system_text("This is the final result of the review. Review these timestamp ranges and adjust them.") is True


def test_is_review_system_text_only_matches_the_exact_final_result_line():
    assert is_review_system_text("This is the final result of the review") is True
    assert is_review_system_text("This is the final result of the review committee report") is False
    assert is_review_system_text("This is the final result of the review. hello better world") is False
    assert is_review_system_text("This is the final result of the review. Review these timestamp ranges and adjust them.") is True


def test_sanitize_review_candidate_text_strips_prompt_echo_prefix_when_remainder_matches_reference():
    assert sanitize_review_candidate_text(
        "This is the final result of the review. hello better world",
        reference_text="hello world",
    ) == "hello better world"


def test_sanitize_review_candidate_text_uses_stripped_reference_when_source_was_already_polluted():
    assert sanitize_review_candidate_text(
        "This is the final result of the review. hello better world",
        reference_text="This is the final result of the review. hello world",
    ) == "hello better world"


def test_sanitize_review_candidate_text_strips_polluted_candidate_even_when_source_matches_verbatim():
    assert sanitize_review_candidate_text(
        "This is the final result of the review. hello world",
        reference_text="This is the final result of the review. hello world",
    ) == "hello world"


def test_sanitize_review_candidate_text_keeps_legitimate_prefixed_lecture_text_when_overlap_is_weak():
    assert sanitize_review_candidate_text(
        "This is the final result of the review committee report",
        reference_text="hello world",
    ) == "This is the final result of the review committee report"


def test_sanitize_review_candidate_text_keeps_exact_clean_source_continuation_text():
    assert sanitize_review_candidate_text(
        "This is the final result of the review committee report",
        reference_text="This is the final result of the review committee report",
    ) == "This is the final result of the review committee report"
    assert sanitize_review_candidate_text(
        "This is the final result of the review and then we continue",
        reference_text="This is the final result of the review and then we continue",
    ) == "This is the final result of the review and then we continue"


def test_sanitize_review_candidate_text_keeps_legitimate_prefixed_lecture_text_when_overlap_is_only_in_tail():
    assert sanitize_review_candidate_text(
        "This is the final result of the review committee report",
        reference_text="committee report",
    ) == "This is the final result of the review committee report"


def test_sanitize_review_candidate_text_keeps_legitimate_colon_prefixed_lecture_text_when_overlap_is_weak():
    assert sanitize_review_candidate_text(
        "This is the final result of the review: committee report",
        reference_text="hello world",
    ) == "This is the final result of the review: committee report"


def test_build_caption_quality_report_reports_explicit_reasons_when_confidence_is_missing():
    segments = [
        TranscriptSegmentTiming(text="Thank you for watching", start=0.0, end=1.0, average_probability=None),
        TranscriptSegmentTiming(text="Thank you for watching", start=1.08, end=2.0, average_probability=None),
        TranscriptSegmentTiming(text="We need to", start=2.2, end=2.6, average_probability=None),
    ]

    report = build_caption_quality_report(segments)

    assert report.average_probability is None
    assert [flag.reason for flag in report.flagged_segments] == [
        "probable duplication",
        "probable truncation",
    ]

    review_text = format_caption_review_document(report)

    assert "Reason: probable duplication" in review_text
    assert "Reason: probable truncation" in review_text
    assert "confidence unknown" not in review_text


def test_build_caption_quality_report_excludes_review_system_segments():
    segments = [
        TranscriptSegmentTiming(text="This is the final result of the review", start=0.0, end=1.0, average_probability=0.12),
        TranscriptSegmentTiming(text="Thank you for watching", start=1.1, end=2.0, average_probability=0.93),
        TranscriptSegmentTiming(text="Thank you for watching", start=2.05, end=3.0, average_probability=0.94),
    ]

    report = build_caption_quality_report(segments)

    assert report.total_segment_count == 2
    assert [flag.reason for flag in report.flagged_segments] == ["probable duplication"]
    review_text = format_caption_review_document(report)
    assert "final result of the review" not in review_text.lower()


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
