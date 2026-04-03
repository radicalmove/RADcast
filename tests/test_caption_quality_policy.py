from __future__ import annotations


def test_reviewed_mode_uses_quality_local_lecture_on_macos_helper():
    from radcast.services.caption_quality_policy import resolve_caption_quality_policy

    policy = resolve_caption_quality_policy(
        quality_mode="reviewed",
        runtime_context="local_helper",
        platform_name="Darwin",
        backend_id="whispercpp",
        first_pass_model_size="medium",
        first_pass_beam_size=3,
        review_model_size="medium",
        review_beam_size=5,
    )

    assert policy.policy_id == "quality_local_lecture"
    assert policy.first_pass_backend_id == "whispercpp"
    assert policy.first_pass_model_size == "medium"
    assert policy.first_pass_beam_size == 3
    assert policy.review_backend_id == "whispercpp"
    assert policy.review_model_size == "medium"
    assert policy.review_beam_size == 5
    assert policy.review_strategy_id == "targeted_review"
    assert policy.cue_shaping_strategy_id == "lecture_friendly"
    assert policy.progress_label == "lecture-quality captions"


def test_reviewed_mode_keeps_standard_policy_off_macos_local_helper():
    from radcast.services.caption_quality_policy import resolve_caption_quality_policy

    policy = resolve_caption_quality_policy(
        quality_mode="reviewed",
        runtime_context="server",
        platform_name="Linux",
        backend_id="faster_whisper",
        first_pass_model_size="medium",
        first_pass_beam_size=3,
        review_model_size="large-v3",
        review_beam_size=5,
    )

    assert policy.policy_id == "standard_reviewed"
    assert policy.first_pass_backend_id == "faster_whisper"
    assert policy.first_pass_model_size == "medium"
    assert policy.first_pass_beam_size == 3
    assert policy.review_backend_id == "faster_whisper"
    assert policy.review_model_size == "large-v3"
    assert policy.review_beam_size == 5
    assert policy.review_strategy_id == "standard_review"
    assert policy.cue_shaping_strategy_id == "standard_caption"
    assert policy.progress_label == "reviewed captions"
