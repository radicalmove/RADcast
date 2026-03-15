from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from radcast.constants import DEFAULT_ENHANCE_COMMAND, DEFAULT_STUDIO_COMMAND
from radcast.models import CaptionFormat, CaptionQualityMode, EnhancementModel, FillerRemovalMode, OutputFormat, SimpleEnhanceRequest
from radcast.services.enhance import (
    EnhanceService,
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
        caption_format=CaptionFormat.SRT,
        max_silence_seconds=1.25,
        remove_filler_words=True,
    )
    assert req.project_id == "proj1"
    assert req.speech_cleanup_requested() is True
    assert req.caption_requested() is True
    assert req.caption_quality_mode == CaptionQualityMode.REVIEWED
    assert req.filler_removal_mode == FillerRemovalMode.AGGRESSIVE


def test_simple_enhance_request_rejects_missing_audio_payload():
    with pytest.raises(ValidationError):
        SimpleEnhanceRequest(
            project_id="proj1",
            input_audio_b64="short",
            input_audio_filename="lecture.wav",
        )


def test_simple_enhance_request_without_cleanup_flags_reports_disabled():
    req = SimpleEnhanceRequest(
        project_id="proj1",
        input_audio_b64="QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVoxMjM0NTY3ODkw",
        input_audio_filename="lecture.wav",
    )

    assert req.speech_cleanup_requested() is False
    assert req.caption_requested() is False


def test_simple_enhance_request_accepts_explicit_filler_cleanup_mode():
    req = SimpleEnhanceRequest(
        project_id="proj1",
        input_audio_b64="QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVoxMjM0NTY3ODkw",
        input_audio_filename="lecture.wav",
        remove_filler_words=True,
        filler_removal_mode=FillerRemovalMode.NORMAL,
    )

    assert req.filler_removal_mode == FillerRemovalMode.NORMAL


def test_simple_enhance_request_accepts_explicit_caption_quality_mode():
    req = SimpleEnhanceRequest(
        project_id="proj1",
        input_audio_b64="QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVoxMjM0NTY3ODkw",
        input_audio_filename="lecture.wav",
        caption_format=CaptionFormat.VTT,
        caption_quality_mode=CaptionQualityMode.FAST,
    )

    assert req.caption_quality_mode == CaptionQualityMode.FAST


def test_simple_enhance_request_accepts_reviewed_caption_mode_and_glossary():
    req = SimpleEnhanceRequest(
        project_id="proj1",
        input_audio_b64="QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVoxMjM0NTY3ODkw",
        input_audio_filename="lecture.wav",
        caption_format=CaptionFormat.VTT,
        caption_quality_mode=CaptionQualityMode.REVIEWED,
        caption_glossary="tikanga Māori, rangatiratanga, organisation",
    )

    assert req.caption_quality_mode == CaptionQualityMode.REVIEWED
    assert req.caption_glossary == "tikanga Māori, rangatiratanga, organisation"


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


def test_resolve_studio_command_prefers_wrapper_binary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    fake_python = tmp_path / "python"
    fake_python.write_text("")
    fake_binary = tmp_path / DEFAULT_STUDIO_COMMAND
    fake_binary.write_text("")

    monkeypatch.setattr("radcast.services.enhance.sys.executable", str(fake_python))

    command = _resolve_command(DEFAULT_STUDIO_COMMAND)

    assert command[0] == str(fake_binary)


def test_estimate_runtime_seconds_scales_with_duration():
    short_runtime = _estimate_runtime_seconds(5, device="cpu", nfe=32, enhancement_model=EnhancementModel.RESEMBLE)
    long_runtime = _estimate_runtime_seconds(30, device="cpu", nfe=32, enhancement_model=EnhancementModel.RESEMBLE)

    assert short_runtime >= 35
    assert long_runtime > short_runtime


def test_no_enhance_runtime_estimate_stays_small():
    short_runtime = _estimate_runtime_seconds(5, device="cpu", nfe=32, enhancement_model=EnhancementModel.NONE)
    long_runtime = _estimate_runtime_seconds(30, device="cpu", nfe=32, enhancement_model=EnhancementModel.NONE)

    assert short_runtime >= 3
    assert long_runtime > short_runtime
    assert long_runtime < 30


def test_studio_runtime_estimate_is_slower_than_resemble_for_same_input():
    resemble_runtime = _estimate_runtime_seconds(30, device="cpu", nfe=32, enhancement_model=EnhancementModel.RESEMBLE)
    studio_runtime = _estimate_runtime_seconds(30, device="cpu", nfe=32, enhancement_model=EnhancementModel.STUDIO)
    studio_v18_runtime = _estimate_runtime_seconds(30, device="cpu", nfe=32, enhancement_model=EnhancementModel.STUDIO_V18)

    assert studio_runtime > resemble_runtime
    assert studio_v18_runtime == studio_runtime


def test_estimate_progress_moves_through_enhancement_band():
    halfway = _estimate_progress(30, 60)
    expected_finish = _estimate_progress(60, 60)
    overtime = _estimate_progress(90, 60)

    assert 0.2 < halfway < expected_finish < overtime < 0.95


def test_estimate_remaining_seconds_hides_unstable_early_estimate():
    assert _estimate_remaining_seconds(4, 60) is None
    assert _estimate_remaining_seconds(25, 60) == 35
    assert _estimate_remaining_seconds(80, 60) is None


def test_enhance_service_applies_prefilter_before_enhancement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    service = EnhanceService()
    source = tmp_path / "input.wav"
    source.write_bytes(b"fake-wav")
    calls: list[str | None] = []

    monkeypatch.setattr("radcast.services.enhance._command_available", lambda _cmd: True)
    monkeypatch.setattr("radcast.services.enhance.probe_duration_seconds", lambda _path: 5.0)

    def fake_convert(src: Path, dst: Path, *, audio_filters: str | None = None) -> None:
        calls.append(audio_filters)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"converted")

    class FakeProc:
        returncode = 0

        def poll(self):
            return 0

        def communicate(self):
            return ("", "")

        def terminate(self):
            return None

    monkeypatch.setattr("radcast.services.enhance.run_ffmpeg_convert", fake_convert)
    monkeypatch.setattr("radcast.services.enhance.subprocess.Popen", lambda *args, **kwargs: FakeProc())
    monkeypatch.setattr(EnhanceService, "_collect_backend_output", lambda self, *, model, out_dir: source)

    final_path = service.enhance(
        job_id="job1",
        enhancement_model="resemble",
        input_audio_path=source,
        output_format=OutputFormat.WAV,
        output_base_path=tmp_path / "out" / "result",
        on_stage=lambda *args: None,
        cancel_check=lambda: False,
    )

    assert final_path.suffix == ".wav"
    assert calls[0] == service.prefilter


def test_no_enhance_model_skips_backend_and_copies_matching_format(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    service = EnhanceService()
    source = tmp_path / "input.mp3"
    source_bytes = b"fake-mp3"
    source.write_bytes(source_bytes)
    backend_called = False

    def fail_backend(*args, **kwargs):
        nonlocal backend_called
        backend_called = True
        raise AssertionError("backend process should not run for the no-enhance model")

    monkeypatch.setattr("radcast.services.enhance.subprocess.Popen", fail_backend)

    final_path = service.enhance(
        job_id="job1",
        enhancement_model=EnhancementModel.NONE,
        input_audio_path=source,
        output_format=OutputFormat.MP3,
        output_base_path=tmp_path / "out" / "result",
        on_stage=lambda *args: None,
        cancel_check=lambda: False,
    )

    assert backend_called is False
    assert final_path.suffix == ".mp3"
    assert final_path.read_bytes() == source_bytes


def test_studio_model_uses_studio_postfilter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    service = EnhanceService()
    source = tmp_path / "input.wav"
    source.write_bytes(b"fake-wav")
    calls: list[str | None] = []

    monkeypatch.setattr("radcast.services.enhance._command_available", lambda _cmd: True)
    monkeypatch.setattr("radcast.services.enhance._python_modules_available", lambda _mods: True)
    monkeypatch.setattr("radcast.services.enhance.probe_duration_seconds", lambda _path: 5.0)

    def fake_convert(src: Path, dst: Path, *, audio_filters: str | None = None) -> None:
        calls.append(audio_filters)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"converted")

    class FakeProc:
        returncode = 0

        def poll(self):
            return 0

        def communicate(self):
            return ("", "")

        def terminate(self):
            return None

    monkeypatch.setattr("radcast.services.enhance.run_ffmpeg_convert", fake_convert)
    monkeypatch.setattr("radcast.services.enhance.subprocess.Popen", lambda *args, **kwargs: FakeProc())
    monkeypatch.setattr(EnhanceService, "_collect_backend_output", lambda self, *, model, out_dir: source)

    final_path = service.enhance(
        job_id="job1",
        enhancement_model=EnhancementModel.STUDIO,
        input_audio_path=source,
        output_format=OutputFormat.MP3,
        output_base_path=tmp_path / "out" / "result",
        on_stage=lambda *args: None,
        cancel_check=lambda: False,
    )

    assert final_path.suffix == ".mp3"
    assert calls[0] == service.prefilter
    assert calls[-1] == service.studio_postfilter


def test_studio_v18_model_uses_studio_v18_postfilter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    service = EnhanceService()
    source = tmp_path / "input.wav"
    source.write_bytes(b"fake-wav")
    calls: list[str | None] = []
    backend_commands: list[list[str]] = []

    monkeypatch.setattr("radcast.services.enhance._command_available", lambda _cmd: True)
    monkeypatch.setattr("radcast.services.enhance._python_modules_available", lambda _mods: True)
    monkeypatch.setattr("radcast.services.enhance.probe_duration_seconds", lambda _path: 5.0)

    def fake_convert(src: Path, dst: Path, *, audio_filters: str | None = None) -> None:
        calls.append(audio_filters)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"converted")

    class FakeProc:
        returncode = 0

        def poll(self):
            return 0

        def communicate(self):
            return ("", "")

        def terminate(self):
            return None

    def fake_popen(command, *args, **kwargs):
        backend_commands.append(command)
        return FakeProc()

    monkeypatch.setattr("radcast.services.enhance.run_ffmpeg_convert", fake_convert)
    monkeypatch.setattr("radcast.services.enhance.subprocess.Popen", fake_popen)
    monkeypatch.setattr(EnhanceService, "_collect_backend_output", lambda self, *, model, out_dir: source)

    final_path = service.enhance(
        job_id="job1",
        enhancement_model=EnhancementModel.STUDIO_V18,
        input_audio_path=source,
        output_format=OutputFormat.MP3,
        output_base_path=tmp_path / "out" / "result",
        on_stage=lambda *args: None,
        cancel_check=lambda: False,
    )

    assert final_path.suffix == ".mp3"
    assert calls == [service.studio_v18_postfilter]
    assert backend_commands
    assert "--dereverb-method" in backend_commands[0]
    assert "nara" in backend_commands[0]
    assert "--nara-chunk-seconds" in backend_commands[0]
    assert service.output_tuning_label_for_model(EnhancementModel.STUDIO_V18) == "RADcast Optimized"
    assert service.output_tuning_label_for_model(EnhancementModel.NONE) is None
