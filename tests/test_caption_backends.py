from __future__ import annotations

import sys
from typing import cast
from types import SimpleNamespace

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


def test_faster_whisper_backend_reports_missing_dependency(monkeypatch):
    from radcast.services import caption_backends

    monkeypatch.setattr(caption_backends, "find_spec", lambda _name: None)
    backend = caption_backends.FasterWhisperCaptionBackend(
        default_model_size="medium",
        device="cpu",
        compute_type="int8",
        transcribe_language="en",
        default_beam_size=3,
    )

    available, detail = backend.capability_status()

    assert available is False
    assert "faster-whisper" in detail


def test_faster_whisper_backend_normalizes_transcription(monkeypatch, tmp_path):
    from radcast.services import caption_backends

    class FakeWhisperModel:
        def __init__(self, model_size, *, device, compute_type):
            self.model_size = model_size
            self.device = device
            self.compute_type = compute_type

        def transcribe(self, _audio_path, **kwargs):
            return iter(
                [
                    SimpleNamespace(
                        start=0.0,
                        end=1.0,
                        text="hello world",
                        words=[
                            SimpleNamespace(word="hello", start=0.0, end=0.4, probability=0.92),
                            SimpleNamespace(word="world", start=0.4, end=1.0, probability=0.93),
                        ],
                    )
                ]
            ), None

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisperModel))
    monkeypatch.setattr(caption_backends, "find_spec", lambda _name: object())

    backend = caption_backends.FasterWhisperCaptionBackend(
        default_model_size="medium",
        device="cpu",
        compute_type="int8",
        transcribe_language="en",
        default_beam_size=3,
    )
    result = backend.transcribe_chunk(tmp_path / "sample.wav", preserve_fillers=False, beam_size=5)

    assert result.model_id == "medium"
    assert result.text == "hello world"
    assert len(result.segments) == 1
    assert result.segments[0].text == "hello world"
    assert len(result.words) == 2
    assert result.words[0].text == "hello"
