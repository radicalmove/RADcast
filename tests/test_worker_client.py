from __future__ import annotations

from radcast.worker_client import _heartbeat_eta_seconds, _heartbeat_progress


def test_heartbeat_eta_counts_down_from_last_real_update():
    assert _heartbeat_eta_seconds(31, 100.0, now_monotonic=104.2) == 27


def test_heartbeat_eta_never_goes_negative():
    assert _heartbeat_eta_seconds(3, 100.0, now_monotonic=109.7) == 0


def test_heartbeat_progress_creeps_forward_within_caption_window():
    progress = _heartbeat_progress(
        0.34,
        stage="captions",
        detail="Transcribing speech for captions. Window 1 of 11. On your local helper device.",
        progress_updated_at_monotonic=100.0,
        cleanup_requested=False,
        caption_requested=True,
        enhancement_requested=False,
        remaining_eta_seconds=660,
        now_monotonic=160.0,
    )

    assert progress > 0.34
    assert progress < 0.38


def test_heartbeat_progress_does_not_creep_without_window_detail():
    progress = _heartbeat_progress(
        0.34,
        stage="captions",
        detail="Transcribing speech for captions. On your local helper device.",
        progress_updated_at_monotonic=100.0,
        cleanup_requested=False,
        caption_requested=True,
        enhancement_requested=False,
        remaining_eta_seconds=660,
        now_monotonic=160.0,
    )

    assert progress == 0.34
