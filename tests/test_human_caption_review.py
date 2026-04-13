from pathlib import Path

from radcast.services.human_caption_review import HumanCaptionReviewStore


def test_saved_review_decision_applies_to_trimmed_rerun_with_same_source_audio(tmp_path: Path):
    store = HumanCaptionReviewStore(tmp_path / "caption_reviews.json")
    store.save_approval(
        source_audio_hash="abc123" * 10,
        absolute_start_seconds=12.4,
        absolute_end_seconds=14.1,
        reason_category="terminology",
        original_text="Aitikanga Māori space",
    )

    decisions = store.match_decisions(
        source_audio_hash="abc123" * 10,
        cue_start_seconds=2.4,
        cue_end_seconds=4.1,
        clip_start_seconds=10.0,
    )

    assert len(decisions) == 1
    assert decisions[0].decision_type == "approved"
    assert decisions[0].reason_category == "terminology"


def test_saved_correction_is_persisted_with_corrected_text_and_timing(tmp_path: Path):
    store = HumanCaptionReviewStore(tmp_path / "caption_reviews.json")
    store.save_correction(
        source_audio_hash="def456" * 10,
        absolute_start_seconds=32.0,
        absolute_end_seconds=34.0,
        reason_category="truncation",
        original_text="We need to",
        corrected_text="We need to understand the concept fully.",
        corrected_start_seconds=31.8,
        corrected_end_seconds=34.4,
    )

    decisions = store.match_decisions(
        source_audio_hash="def456" * 10,
        cue_start_seconds=32.0,
        cue_end_seconds=34.0,
        clip_start_seconds=0.0,
    )

    assert len(decisions) == 1
    assert decisions[0].decision_type == "corrected"
    assert decisions[0].corrected_text == "We need to understand the concept fully."
    assert decisions[0].corrected_start_seconds == 31.8
    assert decisions[0].corrected_end_seconds == 34.4
