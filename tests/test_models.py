from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from radcast.constants import DEFAULT_ENHANCE_COMMAND
from radcast.models import OutputFormat, SimpleEnhanceRequest
from radcast.services.enhance import (
    _estimate_progress,
    _estimate_remaining_seconds,
    _estimate_runtime_seconds,
    _resolve_command,
)


def test_simple_enhance_request_accepts_valid_payload():
    req = SimpleEnhanceRequest(
        project_id="proj1",
        input_audio_b64="QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVoxMjM0NTY3ODkw",
        input_audio_filename="lecture.wav",
        output_format=OutputFormat.MP3,
    )
    assert req.project_id == "proj1"


def test_simple_enhance_request_rejects_missing_audio_payload():
    with pytest.raises(ValidationError):
        SimpleEnhanceRequest(
            project_id="proj1",
            input_audio_b64="short",
            input_audio_filename="lecture.wav",
        )


def test_resolve_command_prefers_sibling_binary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    fake_python = tmp_path / "python"
    fake_python.write_text("")
    fake_binary = tmp_path / "resemble-enhance"
    fake_binary.write_text("")

    monkeypatch.setattr("radcast.services.enhance.sys.executable", str(fake_python))

    command = _resolve_command("resemble-enhance")

    assert command[0] == str(fake_binary)


def test_resolve_default_command_prefers_wrapper_binary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    fake_python = tmp_path / "python"
    fake_python.write_text("")
    fake_binary = tmp_path / DEFAULT_ENHANCE_COMMAND
    fake_binary.write_text("")

    monkeypatch.setattr("radcast.services.enhance.sys.executable", str(fake_python))

    command = _resolve_command(DEFAULT_ENHANCE_COMMAND)

    assert command[0] == str(fake_binary)


def test_estimate_runtime_seconds_scales_with_duration():
    short_runtime = _estimate_runtime_seconds(5, device="cpu", nfe=32)
    long_runtime = _estimate_runtime_seconds(30, device="cpu", nfe=32)

    assert short_runtime >= 35
    assert long_runtime > short_runtime


def test_estimate_progress_moves_through_enhancement_band():
    halfway = _estimate_progress(30, 60)
    expected_finish = _estimate_progress(60, 60)
    overtime = _estimate_progress(90, 60)

    assert 0.2 < halfway < expected_finish < overtime < 0.95


def test_estimate_remaining_seconds_hides_unstable_early_estimate():
    assert _estimate_remaining_seconds(4, 60) is None
    assert _estimate_remaining_seconds(25, 60) == 35
    assert _estimate_remaining_seconds(80, 60) is None
