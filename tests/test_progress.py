from __future__ import annotations

from radcast.models import CaptionQualityMode, FillerRemovalMode
from radcast.progress import (
    estimate_caption_seconds,
    estimate_speech_cleanup_seconds,
    extend_eta_with_cleanup,
    extend_eta_with_postprocess,
    map_cleanup_stage_progress,
    map_postprocess_stage_progress,
    map_worker_stage_progress,
)


def test_cleanup_eta_estimate_scales_with_duration():
    short_eta = estimate_speech_cleanup_seconds(10, remove_filler_words=False)
    long_eta = estimate_speech_cleanup_seconds(120, remove_filler_words=True)
    normal_eta = estimate_speech_cleanup_seconds(
        120,
        remove_filler_words=True,
        filler_removal_mode=FillerRemovalMode.NORMAL,
    )
    aggressive_eta = estimate_speech_cleanup_seconds(
        120,
        remove_filler_words=True,
        filler_removal_mode=FillerRemovalMode.AGGRESSIVE,
    )

    assert short_eta >= 6
    assert long_eta > short_eta
    assert aggressive_eta > normal_eta
    assert estimate_speech_cleanup_seconds(69, remove_filler_words=True, filler_removal_mode=FillerRemovalMode.AGGRESSIVE) >= 180


def test_worker_progress_reserves_band_when_cleanup_enabled():
    without_cleanup = map_worker_stage_progress("finalize", 0.96, reserve_cleanup_band=False)
    with_cleanup = map_worker_stage_progress("finalize", 0.96, reserve_cleanup_band=True)

    assert without_cleanup > with_cleanup
    assert with_cleanup <= 0.58


def test_worker_progress_stays_low_when_enhancement_is_skipped():
    skipped_enhance = map_worker_stage_progress(
        "enhance",
        0.82,
        reserve_cleanup_band=True,
        enhancement_requested=False,
    )

    assert skipped_enhance <= 0.23


def test_cleanup_stage_progress_maps_into_reserved_tail():
    start = map_cleanup_stage_progress(0.0)
    end = map_cleanup_stage_progress(1.0)

    assert 0.58 <= start < end <= 0.93


def test_eta_extension_adds_cleanup_reserve():
    assert extend_eta_with_cleanup(50, 20, reserve_cleanup_band=True) == 70
    assert extend_eta_with_cleanup(None, 20, reserve_cleanup_band=True) is None


def test_caption_progress_uses_tail_after_cleanup():
    cleanup_end = map_postprocess_stage_progress(
        1.0,
        stage="cleanup",
        cleanup_requested=True,
        caption_requested=True,
        enhancement_requested=True,
    )
    caption_start = map_postprocess_stage_progress(
        0.0,
        stage="captions",
        cleanup_requested=True,
        caption_requested=True,
        enhancement_requested=True,
    )

    assert cleanup_end <= caption_start
    assert caption_start >= 0.72


def test_caption_progress_starts_earlier_when_enhancement_is_skipped():
    without_enhancement = map_postprocess_stage_progress(
        0.0,
        stage="captions",
        cleanup_requested=False,
        caption_requested=True,
        enhancement_requested=False,
    )
    with_enhancement = map_postprocess_stage_progress(
        0.0,
        stage="captions",
        cleanup_requested=False,
        caption_requested=True,
        enhancement_requested=True,
    )

    assert without_enhancement < with_enhancement
    assert without_enhancement <= 0.3


def test_cleanup_and_captions_use_lower_band_without_enhancement():
    cleanup_end = map_postprocess_stage_progress(
        1.0,
        stage="cleanup",
        cleanup_requested=True,
        caption_requested=True,
        enhancement_requested=False,
    )
    caption_start = map_postprocess_stage_progress(
        0.0,
        stage="captions",
        cleanup_requested=True,
        caption_requested=True,
        enhancement_requested=False,
    )

    assert cleanup_end <= caption_start
    assert caption_start < 0.72


def test_postprocess_eta_extension_adds_cleanup_and_caption_time():
    assert estimate_caption_seconds(30, quality_mode=CaptionQualityMode.FAST) >= 20
    assert estimate_caption_seconds(120, quality_mode=CaptionQualityMode.ACCURATE) >= 150
    assert estimate_caption_seconds(120, quality_mode=CaptionQualityMode.ACCURATE) > estimate_caption_seconds(
        120,
        quality_mode=CaptionQualityMode.FAST,
    )
    assert estimate_caption_seconds(120, quality_mode=CaptionQualityMode.REVIEWED) > estimate_caption_seconds(
        120,
        quality_mode=CaptionQualityMode.ACCURATE,
    )
    assert extend_eta_with_postprocess(50, 20, 8, reserve_postprocess_band=True) == 78
