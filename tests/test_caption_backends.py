from __future__ import annotations

import json
import sys
from pathlib import Path
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


def test_whispercpp_backend_reports_missing_binary(monkeypatch):
    from radcast.services import caption_backends

    monkeypatch.setattr(caption_backends.shutil, "which", lambda _name: None)
    backend = caption_backends.WhisperCppCaptionBackend(
        default_model_size="small",
        transcribe_language="en",
        default_beam_size=3,
    )

    available, detail = backend.capability_status()

    assert available is False
    assert "whisper.cpp" in detail


def test_whispercpp_backend_runs_cli_and_normalizes_json(monkeypatch, tmp_path):
    from radcast.services import caption_backends

    binary_path = tmp_path / "whisper-cli"
    binary_path.write_text("#!/bin/sh\n", encoding="utf-8")
    model_path = tmp_path / "ggml-small.bin"
    model_path.write_bytes(b"demo-model")
    recorded: dict[str, list[str]] = {}

    def fake_run(cmd, capture_output, text, check):
        recorded["cmd"] = list(cmd)
        output_base = cmd[cmd.index("--output-file") + 1]
        json_path = Path(output_base).with_suffix(".json")
        json_path.write_text(
            json.dumps(
                {
                    "transcription": [
                        {
                            "text": "hello world",
                            "offsets": {"from": 0, "to": 120},
                            "words": [
                                {"text": "hello", "t0": 0, "t1": 45, "p": 0.91},
                                {"text": "world", "t0": 45, "t1": 120, "p": 0.94},
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(caption_backends.subprocess, "run", fake_run)
    backend = caption_backends.WhisperCppCaptionBackend(
        default_model_size="small",
        transcribe_language="en",
        default_beam_size=3,
        binary_path=str(binary_path),
        model_dir=str(tmp_path),
        use_gpu=False,
    )

    result = backend.transcribe_chunk(
        tmp_path / "sample.wav",
        preserve_fillers=False,
        beam_size=5,
        initial_prompt="Prompt text",
    )

    assert recorded["cmd"][0] == str(binary_path)
    assert "--output-json-full" in recorded["cmd"]
    assert "--output-file" in recorded["cmd"]
    assert "--max-context" in recorded["cmd"]
    assert "--no-gpu" in recorded["cmd"]
    assert "--prompt" in recorded["cmd"]
    assert result.model_id == "small"
    assert result.text == "hello world"
    assert len(result.segments) == 1
    assert result.segments[0].start == pytest.approx(0.0)
    assert result.segments[0].end == pytest.approx(1.2)
    assert len(result.words) == 2
    assert result.words[1].text == "world"


def test_mlx_whisper_backend_reports_missing_dependency(monkeypatch):
    from radcast.services import caption_backends

    monkeypatch.setattr(caption_backends, "find_spec", lambda _name: None)
    backend = caption_backends.MlxWhisperCaptionBackend(
        default_model_size="medium",
        transcribe_language="en",
    )

    available, detail = backend.capability_status()

    assert available is False
    assert "mlx-whisper" in detail


def test_mlx_whisper_backend_normalizes_transcription(monkeypatch, tmp_path):
    from radcast.services import caption_backends

    def fake_transcribe(audio_path, *, path_or_hf_repo, word_timestamps, language, initial_prompt, condition_on_previous_text):
        assert str(audio_path).endswith("sample.wav")
        assert path_or_hf_repo == "mlx-community/whisper-medium"
        assert word_timestamps is True
        assert language == "en"
        assert initial_prompt == "Prompt text"
        assert condition_on_previous_text is True
        return {
            "text": "hello world",
            "segments": [
                {
                    "start": 0.0,
                    "end": 1.0,
                    "text": "hello world",
                    "avg_logprob": -0.2,
                    "words": [
                        {"word": "hello", "start": 0.0, "end": 0.4, "probability": 0.92},
                        {"word": "world", "start": 0.4, "end": 1.0, "probability": 0.94},
                    ],
                }
            ],
        }

    monkeypatch.setitem(sys.modules, "mlx_whisper", SimpleNamespace(transcribe=fake_transcribe))
    monkeypatch.setattr(caption_backends, "find_spec", lambda _name: object())

    backend = caption_backends.MlxWhisperCaptionBackend(
        default_model_size="medium",
        transcribe_language="en",
    )
    result = backend.transcribe_chunk(
        tmp_path / "sample.wav",
        preserve_fillers=False,
        model_size="medium",
        condition_on_previous_text=True,
        initial_prompt="Prompt text",
    )

    assert result.model_id == "medium"
    assert result.text == "hello world"
    assert len(result.segments) == 1
    assert result.segments[0].text == "hello world"
    assert len(result.words) == 2
    assert result.words[0].text == "hello"
