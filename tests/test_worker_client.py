from __future__ import annotations

from radcast.worker_client import _heartbeat_eta_seconds


def test_heartbeat_eta_counts_down_from_last_real_update():
    assert _heartbeat_eta_seconds(31, 100.0, now_monotonic=104.2) == 27


def test_heartbeat_eta_never_goes_negative():
    assert _heartbeat_eta_seconds(3, 100.0, now_monotonic=109.7) == 0
