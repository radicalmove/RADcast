from __future__ import annotations

from radcast.progress import (
    estimate_speech_cleanup_seconds,
    extend_eta_with_cleanup,
    map_cleanup_stage_progress,
    map_worker_stage_progress,
)


def test_cleanup_eta_estimate_scales_with_duration():
    short_eta = estimate_speech_cleanup_seconds(10, remove_filler_words=False)
    long_eta = estimate_speech_cleanup_seconds(120, remove_filler_words=True)

    assert short_eta >= 6
    assert long_eta > short_eta


def test_worker_progress_reserves_band_when_cleanup_enabled():
    without_cleanup = map_worker_stage_progress("finalize", 0.96, reserve_cleanup_band=False)
    with_cleanup = map_worker_stage_progress("finalize", 0.96, reserve_cleanup_band=True)

    assert without_cleanup > with_cleanup
    assert with_cleanup <= 0.84


def test_cleanup_stage_progress_maps_into_reserved_tail():
    start = map_cleanup_stage_progress(0.965)
    end = map_cleanup_stage_progress(0.985)

    assert 0.84 <= start < end <= 0.96


def test_eta_extension_adds_cleanup_reserve():
    assert extend_eta_with_cleanup(50, 20, reserve_cleanup_band=True) == 70
    assert extend_eta_with_cleanup(None, 20, reserve_cleanup_band=True) is None
