from __future__ import annotations

import pytest


def test_auto_prefers_whispercpp_for_macos_local_helper_when_available():
    from radcast.services.caption_backend_selection import resolve_caption_backend_id

    resolved = resolve_caption_backend_id(
        requested_backend="auto",
        platform_name="darwin",
        runtime_context="local_helper",
        available_backends={"faster_whisper", "whispercpp"},
    )

    assert resolved == "whispercpp"


def test_auto_prefers_faster_whisper_for_windows():
    from radcast.services.caption_backend_selection import resolve_caption_backend_id

    resolved = resolve_caption_backend_id(
        requested_backend="auto",
        platform_name="windows",
        runtime_context="local_helper",
        available_backends={"faster_whisper"},
    )

    assert resolved == "faster_whisper"


def test_explicit_override_beats_auto():
    from radcast.services.caption_backend_selection import resolve_caption_backend_id

    resolved = resolve_caption_backend_id(
        requested_backend="faster_whisper",
        platform_name="darwin",
        runtime_context="local_helper",
        available_backends={"faster_whisper", "whispercpp"},
    )

    assert resolved == "faster_whisper"


def test_missing_explicit_backend_raises():
    from radcast.services.caption_backend_selection import CaptionBackendSelectionError, resolve_caption_backend_id

    with pytest.raises(CaptionBackendSelectionError):
        resolve_caption_backend_id(
            requested_backend="whispercpp",
            platform_name="darwin",
            runtime_context="local_helper",
            available_backends={"faster_whisper"},
        )


def test_auto_falls_back_to_faster_whisper_when_whispercpp_unavailable():
    from radcast.services.caption_backend_selection import resolve_caption_backend_id

    resolved = resolve_caption_backend_id(
        requested_backend="auto",
        platform_name="darwin",
        runtime_context="local_helper",
        available_backends={"faster_whisper"},
    )

    assert resolved == "faster_whisper"
