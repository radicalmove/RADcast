from __future__ import annotations

from typing import cast

import pytest


def test_transcription_result_normalizes_segments():
    from radcast.services.caption_backends import CaptionSegment, CaptionTranscriptionResult

    result = CaptionTranscriptionResult(
        text="hello world",
        segments=[CaptionSegment(start=0.0, end=1.0, text="hello world", average_probability=-0.1)],
        words=[],
        model_id="demo",
    )

    assert result.text == "hello world"
    assert result.model_id == "demo"
    assert result.segments[0].text == "hello world"


def test_caption_backend_protocol_requires_capability_and_transcription_methods():
    from radcast.services.caption_backends import CaptionBackend

    class DemoBackend:
        id = "demo"

        def capability_status(self) -> tuple[bool, str]:
            return True, "ready"

        def transcribe_chunk(self, audio_path, **kwargs):
            raise NotImplementedError

    backend = cast(CaptionBackend, DemoBackend())
    available, detail = backend.capability_status()

    assert available is True
    assert detail == "ready"
    assert backend.id == "demo"


def test_caption_segment_requires_non_negative_range():
    from radcast.services.caption_backends import CaptionSegment

    with pytest.raises(ValueError):
        CaptionSegment(start=1.0, end=0.5, text="bad")
