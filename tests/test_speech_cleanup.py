from __future__ import annotations

import shutil
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from radcast.models import CaptionFormat, CaptionQualityMode, FillerRemovalMode, OutputFormat
from radcast.services.speech_cleanup import (
    CaptionExportResult,
    SpeechCleanupResult,
    SpeechCleanupService,
    TranscriptSegmentTiming,
    TranscriptWordTiming,
    _caption_review_flag_budget,
    _compose_accessible_caption_blocks,
    _clean_caption_text,
    _dedupe_adjacent_caption_blocks,
    _format_caption_document,
    _build_caption_prompt,
    _collect_timing_rows,
    _transcription_eta_seconds,
    _windowed_transcription_eta_seconds,
    _read_pcm16_wav,
)


def _write_test_wav(path: Path, samples: np.ndarray, *, sample_rate: int = 16000) -> None:
    clipped = np.clip(samples, -1.0, 1.0 - (1.0 / 32768.0))
    pcm = np.round(clipped * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def _wav_duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


def test_read_pcm16_wav_falls_back_to_soundfile_on_wave_error(monkeypatch, tmp_path: Path):
    sample_rate = 16000
    tone_t = np.linspace(0.0, 0.25, int(sample_rate * 0.25), endpoint=False)
    audio = (0.2 * np.sin(2.0 * np.pi * 220.0 * tone_t)).astype(np.float32)
    audio_path = tmp_path / "analysis.wav"
    _write_test_wav(audio_path, audio, sample_rate=sample_rate)

    def fake_wave_open(*args, **kwargs):
        raise wave.Error("unknown format: 65534")

    monkeypatch.setattr("radcast.services.speech_cleanup.wave.open", fake_wave_open)

    waveform, detected_sample_rate = _read_pcm16_wav(audio_path)

    assert detected_sample_rate == sample_rate
    assert waveform.shape == (audio.shape[0], 1)
    assert np.isclose(float(np.max(np.abs(waveform))), 0.2, atol=0.02)


def test_cleanup_audio_file_shortens_long_speech_gap(monkeypatch, tmp_path: Path):
    sample_rate = 16000
    tone_t = np.linspace(0.0, 0.35, int(sample_rate * 0.35), endpoint=False)
    speech_a = 0.2 * np.sin(2.0 * np.pi * 220.0 * tone_t)
    speech_b = 0.2 * np.sin(2.0 * np.pi * 330.0 * tone_t)
    silence = np.zeros(int(sample_rate * 1.2), dtype=np.float32)
    audio = np.concatenate([speech_a, silence, speech_b]).astype(np.float32)
    audio_path = tmp_path / "lecture.wav"
    _write_test_wav(audio_path, audio, sample_rate=sample_rate)
    original_duration = _wav_duration_seconds(audio_path)

    service = SpeechCleanupService()
    monkeypatch.setattr(service, "capability_status", lambda: (True, "ready"))
    monkeypatch.setattr(
        service,
        "_transcribe_timeline",
        lambda _path, **kwargs: (
            [
                TranscriptWordTiming(text="hello", start=0.0, end=0.34, probability=0.95),
                TranscriptWordTiming(text="world", start=1.55, end=1.9, probability=0.95),
            ],
            [],
        ),
    )
    monkeypatch.setattr("radcast.services.speech_cleanup.run_ffmpeg_convert", lambda src, dst, *, audio_filters=None: shutil.copy2(src, dst))
    monkeypatch.setattr("radcast.services.speech_cleanup.probe_duration_seconds", _wav_duration_seconds)

    result = service.cleanup_audio_file(
        audio_path=audio_path,
        output_format=OutputFormat.WAV,
        max_silence_seconds=0.4,
        remove_filler_words=False,
    )

    assert result.applied is True
    assert result.removed_pause_count == 1
    assert result.removed_filler_count == 0
    assert result.duration_seconds < original_duration
    assert 1.0 <= result.duration_seconds <= 1.2


def test_cleanup_audio_file_removes_isolated_filler_word(monkeypatch, tmp_path: Path):
    sample_rate = 16000
    tone_t = np.linspace(0.0, 0.35, int(sample_rate * 0.35), endpoint=False)
    speech_a = 0.18 * np.sin(2.0 * np.pi * 220.0 * tone_t)
    speech_b = 0.18 * np.sin(2.0 * np.pi * 330.0 * tone_t)
    filler_t = np.linspace(0.0, 0.24, int(sample_rate * 0.24), endpoint=False)
    filler = 0.12 * np.sin(2.0 * np.pi * 180.0 * filler_t)
    gap_a = np.zeros(int(sample_rate * 0.16), dtype=np.float32)
    gap_b = np.zeros(int(sample_rate * 0.18), dtype=np.float32)
    audio = np.concatenate([speech_a, gap_a, filler, gap_b, speech_b]).astype(np.float32)
    audio_path = tmp_path / "lecture.wav"
    _write_test_wav(audio_path, audio, sample_rate=sample_rate)
    original_duration = _wav_duration_seconds(audio_path)

    service = SpeechCleanupService()
    monkeypatch.setattr(service, "capability_status", lambda: (True, "ready"))
    monkeypatch.setattr(
        service,
        "_transcribe_timeline",
        lambda _path, **kwargs: (
            [
                TranscriptWordTiming(text="hello", start=0.0, end=0.34, probability=0.93),
                TranscriptWordTiming(text="um", start=0.50, end=0.73, probability=0.88),
                TranscriptWordTiming(text="again", start=0.92, end=1.27, probability=0.91),
            ],
            [],
        ),
    )
    monkeypatch.setattr("radcast.services.speech_cleanup.run_ffmpeg_convert", lambda src, dst, *, audio_filters=None: shutil.copy2(src, dst))
    monkeypatch.setattr("radcast.services.speech_cleanup.probe_duration_seconds", _wav_duration_seconds)

    result = service.cleanup_audio_file(
        audio_path=audio_path,
        output_format=OutputFormat.WAV,
        max_silence_seconds=None,
        remove_filler_words=True,
    )

    assert result.applied is True
    assert result.removed_pause_count == 0
    assert result.removed_filler_count == 1
    assert result.duration_seconds < original_duration
    assert result.duration_seconds < 1.25


def test_cleanup_audio_file_removes_elongated_filler_with_asymmetric_context(monkeypatch, tmp_path: Path):
    sample_rate = 16000
    tone_t = np.linspace(0.0, 0.30, int(sample_rate * 0.30), endpoint=False)
    speech_a = 0.18 * np.sin(2.0 * np.pi * 220.0 * tone_t)
    speech_b = 0.18 * np.sin(2.0 * np.pi * 330.0 * tone_t)
    filler_t = np.linspace(0.0, 0.28, int(sample_rate * 0.28), endpoint=False)
    filler = 0.11 * np.sin(2.0 * np.pi * 170.0 * filler_t)
    gap_a = np.zeros(int(sample_rate * 0.04), dtype=np.float32)
    gap_b = np.zeros(int(sample_rate * 0.18), dtype=np.float32)
    audio = np.concatenate([speech_a, gap_a, filler, gap_b, speech_b]).astype(np.float32)
    audio_path = tmp_path / "lecture.wav"
    _write_test_wav(audio_path, audio, sample_rate=sample_rate)
    original_duration = _wav_duration_seconds(audio_path)

    service = SpeechCleanupService()
    monkeypatch.setattr(service, "capability_status", lambda: (True, "ready"))
    monkeypatch.setattr(
        service,
        "_transcribe_timeline",
        lambda _path, **kwargs: (
            [
                TranscriptWordTiming(text="right", start=0.0, end=0.29, probability=0.91),
                TranscriptWordTiming(text="ummm", start=0.33, end=0.61, probability=0.36),
                TranscriptWordTiming(text="then", start=0.79, end=1.08, probability=0.9),
            ],
            [],
        ),
    )
    monkeypatch.setattr("radcast.services.speech_cleanup.run_ffmpeg_convert", lambda src, dst, *, audio_filters=None: shutil.copy2(src, dst))
    monkeypatch.setattr("radcast.services.speech_cleanup.probe_duration_seconds", _wav_duration_seconds)

    result = service.cleanup_audio_file(
        audio_path=audio_path,
        output_format=OutputFormat.WAV,
        max_silence_seconds=None,
        remove_filler_words=True,
    )

    assert result.applied is True
    assert result.removed_filler_count == 1
    assert result.duration_seconds < original_duration


def test_cleanup_audio_file_removes_low_gap_filler_with_pause_on_both_sides(monkeypatch, tmp_path: Path):
    sample_rate = 16000
    tone_t = np.linspace(0.0, 0.30, int(sample_rate * 0.30), endpoint=False)
    speech_a = 0.18 * np.sin(2.0 * np.pi * 210.0 * tone_t)
    speech_b = 0.18 * np.sin(2.0 * np.pi * 300.0 * tone_t)
    filler_t = np.linspace(0.0, 0.13, int(sample_rate * 0.13), endpoint=False)
    filler = 0.1 * np.sin(2.0 * np.pi * 170.0 * filler_t)
    gap_a = np.zeros(int(sample_rate * 0.06), dtype=np.float32)
    gap_b = np.zeros(int(sample_rate * 0.06), dtype=np.float32)
    audio = np.concatenate([speech_a, gap_a, filler, gap_b, speech_b]).astype(np.float32)
    audio_path = tmp_path / "lecture.wav"
    _write_test_wav(audio_path, audio, sample_rate=sample_rate)
    original_duration = _wav_duration_seconds(audio_path)

    service = SpeechCleanupService()
    monkeypatch.setattr(service, "capability_status", lambda: (True, "ready"))
    monkeypatch.setattr(
        service,
        "_transcribe_timeline",
        lambda _path, **kwargs: (
            [
                TranscriptWordTiming(text="hello", start=0.0, end=0.30, probability=0.95),
                TranscriptWordTiming(text="uh", start=0.36, end=0.49, probability=0.27),
                TranscriptWordTiming(text="again", start=0.55, end=0.85, probability=0.92),
            ],
            [],
        ),
    )
    monkeypatch.setattr("radcast.services.speech_cleanup.run_ffmpeg_convert", lambda src, dst, *, audio_filters=None: shutil.copy2(src, dst))
    monkeypatch.setattr("radcast.services.speech_cleanup.probe_duration_seconds", _wav_duration_seconds)

    result = service.cleanup_audio_file(
        audio_path=audio_path,
        output_format=OutputFormat.WAV,
        max_silence_seconds=None,
        remove_filler_words=True,
    )

    assert result.applied is True
    assert result.removed_filler_count == 1
    assert result.duration_seconds < original_duration


def test_cleanup_audio_file_removes_lower_confidence_conversational_filler(monkeypatch, tmp_path: Path):
    sample_rate = 16000
    tone_t = np.linspace(0.0, 0.28, int(sample_rate * 0.28), endpoint=False)
    speech_a = 0.18 * np.sin(2.0 * np.pi * 205.0 * tone_t)
    speech_b = 0.18 * np.sin(2.0 * np.pi * 295.0 * tone_t)
    filler_t = np.linspace(0.0, 0.11, int(sample_rate * 0.11), endpoint=False)
    filler = 0.09 * np.sin(2.0 * np.pi * 165.0 * filler_t)
    gap_a = np.zeros(int(sample_rate * 0.035), dtype=np.float32)
    gap_b = np.zeros(int(sample_rate * 0.04), dtype=np.float32)
    audio = np.concatenate([speech_a, gap_a, filler, gap_b, speech_b]).astype(np.float32)
    audio_path = tmp_path / "lecture.wav"
    _write_test_wav(audio_path, audio, sample_rate=sample_rate)
    original_duration = _wav_duration_seconds(audio_path)

    service = SpeechCleanupService()
    monkeypatch.setattr(service, "capability_status", lambda: (True, "ready"))
    monkeypatch.setattr(
        service,
        "_transcribe_timeline",
        lambda _path, **kwargs: (
            [
                TranscriptWordTiming(text="well", start=0.0, end=0.28, probability=0.94),
                TranscriptWordTiming(text="ah", start=0.315, end=0.425, probability=0.19),
                TranscriptWordTiming(text="right", start=0.465, end=0.745, probability=0.91),
            ],
            [],
        ),
    )
    monkeypatch.setattr("radcast.services.speech_cleanup.run_ffmpeg_convert", lambda src, dst, *, audio_filters=None: shutil.copy2(src, dst))
    monkeypatch.setattr("radcast.services.speech_cleanup.probe_duration_seconds", _wav_duration_seconds)

    result = service.cleanup_audio_file(
        audio_path=audio_path,
        output_format=OutputFormat.WAV,
        max_silence_seconds=None,
        remove_filler_words=True,
    )

    assert result.applied is True
    assert result.removed_filler_count == 1
    assert result.duration_seconds < original_duration


def test_cleanup_audio_file_aggressive_mode_removes_more_low_confidence_fillers(monkeypatch, tmp_path: Path):
    sample_rate = 16000
    tone_t = np.linspace(0.0, 0.28, int(sample_rate * 0.28), endpoint=False)
    speech_a = 0.18 * np.sin(2.0 * np.pi * 205.0 * tone_t)
    speech_b = 0.18 * np.sin(2.0 * np.pi * 295.0 * tone_t)
    filler_t = np.linspace(0.0, 0.11, int(sample_rate * 0.11), endpoint=False)
    filler = 0.09 * np.sin(2.0 * np.pi * 165.0 * filler_t)
    gap_a = np.zeros(int(sample_rate * 0.035), dtype=np.float32)
    gap_b = np.zeros(int(sample_rate * 0.04), dtype=np.float32)
    audio = np.concatenate([speech_a, gap_a, filler, gap_b, speech_b]).astype(np.float32)
    normal_path = tmp_path / "lecture-normal.wav"
    aggressive_path = tmp_path / "lecture-aggressive.wav"
    _write_test_wav(normal_path, audio, sample_rate=sample_rate)
    _write_test_wav(aggressive_path, audio, sample_rate=sample_rate)
    original_duration = _wav_duration_seconds(normal_path)

    service = SpeechCleanupService()
    monkeypatch.setattr(service, "capability_status", lambda: (True, "ready"))
    monkeypatch.setattr(
        service,
        "_transcribe_timeline",
        lambda _path, **kwargs: (
            [
                TranscriptWordTiming(text="well", start=0.0, end=0.28, probability=0.94),
                TranscriptWordTiming(text="ah", start=0.315, end=0.425, probability=0.01),
                TranscriptWordTiming(text="right", start=0.465, end=0.745, probability=0.91),
            ],
            [],
        ),
    )
    monkeypatch.setattr("radcast.services.speech_cleanup.run_ffmpeg_convert", lambda src, dst, *, audio_filters=None: shutil.copy2(src, dst))
    monkeypatch.setattr("radcast.services.speech_cleanup.probe_duration_seconds", _wav_duration_seconds)

    normal_result = service.cleanup_audio_file(
        audio_path=normal_path,
        output_format=OutputFormat.WAV,
        max_silence_seconds=None,
        remove_filler_words=True,
        filler_removal_mode=FillerRemovalMode.NORMAL,
    )
    aggressive_result = service.cleanup_audio_file(
        audio_path=aggressive_path,
        output_format=OutputFormat.WAV,
        max_silence_seconds=None,
        remove_filler_words=True,
        filler_removal_mode=FillerRemovalMode.AGGRESSIVE,
    )

    assert normal_result.applied is False
    assert normal_result.removed_filler_count == 0
    assert aggressive_result.applied is True
    assert aggressive_result.removed_filler_count == 1
    assert aggressive_result.duration_seconds < original_duration


def test_transcribe_timeline_aggressive_mode_uses_windowed_prompted_pass(monkeypatch, tmp_path: Path):
    sample_rate = 16000
    audio = np.zeros(int(sample_rate * 12.2), dtype=np.float32)
    audio_path = tmp_path / "analysis.wav"
    _write_test_wav(audio_path, audio, sample_rate=sample_rate)

    service = SpeechCleanupService()
    calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(service, "_load_model", lambda _model_size=None: object())

    def fake_transcribe_file_with_info(
        _model,
        clip_path: Path,
        *,
        preserve_fillers: bool,
        beam_size: int | None = None,
        condition_on_previous_text: bool = False,
        initial_prompt: str | None = None,
        language_override: str | None = None,
        vad_filter_override: bool | None = None,
    ):
        calls.append((clip_path.name, preserve_fillers))
        if clip_path.name == "window_000000.wav":
            return [
                SimpleNamespace(
                    start=1.2,
                    end=1.45,
                    text="um",
                    words=[SimpleNamespace(start=1.2, end=1.45, word="um", probability=0.02)],
                )
            ], SimpleNamespace()
        if clip_path.name == "window_006000.wav":
            return [
                SimpleNamespace(
                    start=1.1,
                    end=1.34,
                    text="uh",
                    words=[SimpleNamespace(start=1.1, end=1.34, word="uh", probability=0.01)],
                )
            ], SimpleNamespace()
        return [], SimpleNamespace()

    monkeypatch.setattr(service, "_transcribe_file_with_info", fake_transcribe_file_with_info)

    words, _segments = service._transcribe_timeline(
        audio_path,
        total_duration=12.2,
        started_at=0.0,
        cleanup_eta_seconds=30,
        on_stage=None,
        remove_filler_words=True,
        filler_removal_mode=FillerRemovalMode.AGGRESSIVE,
    )

    assert ("window_000000.wav", True) in calls
    assert ("window_006000.wav", True) in calls
    assert all(preserve_fillers for _, preserve_fillers in calls)
    assert [word.text for word in words] == ["um", "uh"]
    assert words[0].start == 1.2
    assert words[1].start == 7.1


def test_generate_caption_file_writes_srt(monkeypatch, tmp_path: Path):
    sample_rate = 16000
    audio = np.zeros(int(sample_rate * 2.0), dtype=np.float32)
    audio_path = tmp_path / "lecture.wav"
    _write_test_wav(audio_path, audio, sample_rate=sample_rate)

    service = SpeechCleanupService()
    monkeypatch.setattr(service, "capability_status", lambda: (True, "ready"))
    monkeypatch.setattr("radcast.services.speech_cleanup.run_ffmpeg_convert", lambda src, dst: shutil.copy2(src, dst))
    monkeypatch.setattr(
        service,
        "_transcribe_timeline",
        lambda *args, **kwargs: (
            [],
            [
                TranscriptSegmentTiming(text="Hello world", start=0.0, end=1.25),
                TranscriptSegmentTiming(text="Second line", start=1.4, end=1.95),
            ],
        ),
    )

    result = service.generate_caption_file(audio_path=audio_path, caption_format=CaptionFormat.SRT)

    assert isinstance(result, CaptionExportResult)
    assert result.caption_path.suffix == ".srt"
    text = result.caption_path.read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:01,250" in text
    assert "Hello world" in text
    assert "Second line" in text


def test_generate_caption_file_writes_vtt(monkeypatch, tmp_path: Path):
    sample_rate = 16000
    audio = np.zeros(int(sample_rate * 1.5), dtype=np.float32)
    audio_path = tmp_path / "lecture.wav"
    _write_test_wav(audio_path, audio, sample_rate=sample_rate)

    service = SpeechCleanupService()
    monkeypatch.setattr(service, "capability_status", lambda: (True, "ready"))
    monkeypatch.setattr("radcast.services.speech_cleanup.run_ffmpeg_convert", lambda src, dst: shutil.copy2(src, dst))
    monkeypatch.setattr(
        service,
        "_transcribe_timeline",
        lambda *args, **kwargs: (
            [],
            [TranscriptSegmentTiming(text="Caption text", start=0.0, end=0.9)],
        ),
    )

    result = service.generate_caption_file(audio_path=audio_path, caption_format=CaptionFormat.VTT)

    assert result.caption_path.suffix == ".vtt"
    text = result.caption_path.read_text(encoding="utf-8")
    assert text.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:00.900" in text
    assert "Caption text" in text


def test_collect_timing_rows_trims_segment_text_to_kept_words():
    segment = SimpleNamespace(
        start=0.0,
        end=2.0,
        text="Kia ora and welcome",
        words=[
            SimpleNamespace(word="Kia", start=0.0, end=0.28, probability=0.91),
            SimpleNamespace(word="ora", start=0.31, end=0.58, probability=0.9),
            SimpleNamespace(word="and", start=0.72, end=0.94, probability=0.89),
            SimpleNamespace(word="welcome", start=1.25, end=1.72, probability=0.88),
        ],
    )

    words, segments = _collect_timing_rows(
        [segment],
        window_offset_seconds=10.0,
        keep_start_seconds=0.65,
        keep_end_seconds=1.05,
    )

    assert [word.text for word in words] == ["and"]
    assert len(segments) == 1
    assert segments[0].text == "and"
    assert segments[0].start == 10.65
    assert segments[0].end == 11.05


def test_generate_caption_file_uses_accurate_profile_and_maori_glossary(monkeypatch, tmp_path: Path):
    sample_rate = 16000
    audio = np.zeros(int(sample_rate * 1.5), dtype=np.float32)
    audio_path = tmp_path / "lecture.wav"
    _write_test_wav(audio_path, audio, sample_rate=sample_rate)

    service = SpeechCleanupService()
    monkeypatch.setattr(service, "capability_status", lambda: (True, "ready"))
    monkeypatch.setattr("radcast.services.speech_cleanup.run_ffmpeg_convert", lambda src, dst: shutil.copy2(src, dst))

    captured: dict[str, object] = {}

    def fake_transcribe_timeline(*args, **kwargs):
        captured.update(kwargs)
        return [], [TranscriptSegmentTiming(text="Caption text", start=0.0, end=0.9)]

    monkeypatch.setattr(service, "_transcribe_timeline", fake_transcribe_timeline)

    service.generate_caption_file(
        audio_path=audio_path,
        caption_format=CaptionFormat.VTT,
        caption_quality_mode=CaptionQualityMode.ACCURATE,
    )

    assert captured["model_size"] == service.caption_accurate_model_size
    assert captured["beam_size"] == service.caption_accurate_beam_size
    assert captured["condition_on_previous_text"] is True
    assert captured["window_seconds"] == 12.0
    assert captured["overlap_seconds"] == 2.5
    assert "tikanga" in str(captured["initial_prompt"])
    assert "whānau" in str(captured["initial_prompt"])
    assert "organisation" in str(captured["initial_prompt"])


def test_generate_reviewed_caption_file_uses_larger_windows_for_long_audio(monkeypatch, tmp_path: Path):
    sample_rate = 16000
    audio = np.zeros(int(sample_rate * 350.0), dtype=np.float32)
    audio_path = tmp_path / "lecture.wav"
    _write_test_wav(audio_path, audio, sample_rate=sample_rate)

    service = SpeechCleanupService()
    monkeypatch.setattr(service, "capability_status", lambda: (True, "ready"))
    monkeypatch.setattr("radcast.services.speech_cleanup.run_ffmpeg_convert", lambda src, dst: shutil.copy2(src, dst))

    captured: dict[str, object] = {}

    def fake_transcribe_timeline(*args, **kwargs):
        captured.update(kwargs)
        return [], [TranscriptSegmentTiming(text="Caption text", start=0.0, end=0.9)]

    monkeypatch.setattr(service, "_transcribe_timeline", fake_transcribe_timeline)

    service.generate_caption_file(
        audio_path=audio_path,
        caption_format=CaptionFormat.VTT,
        caption_quality_mode=CaptionQualityMode.REVIEWED,
    )

    assert captured["window_seconds"] == 42.0
    assert captured["overlap_seconds"] == 1.5


def test_caption_transcribe_file_does_not_force_english_when_caption_language_is_auto(monkeypatch, tmp_path: Path):
    sample_rate = 16000
    audio = np.zeros(int(sample_rate * 0.8), dtype=np.float32)
    audio_path = tmp_path / "caption.wav"
    _write_test_wav(audio_path, audio, sample_rate=sample_rate)

    service = SpeechCleanupService()
    service.transcribe_language = "en"

    captured: dict[str, object] = {}

    class FakeModel:
        def transcribe(self, path: str, **kwargs):
            captured.update(kwargs)
            return iter([]), SimpleNamespace()

    list(
        service._transcribe_file(
            FakeModel(),
            audio_path,
            preserve_fillers=False,
            language_override="auto",
        )
    )

    assert "language" not in captured


def test_transcribe_windowed_timeline_reuses_detected_language_and_disables_vad_for_dense_speech(monkeypatch, tmp_path: Path):
    sample_rate = 16000
    audio = np.zeros(int(sample_rate * 70.0), dtype=np.float32)
    audio_path = tmp_path / "caption.wav"
    _write_test_wav(audio_path, audio, sample_rate=sample_rate)

    service = SpeechCleanupService()
    monkeypatch.setattr(service, "_load_model", lambda _model_size=None: FakeModel())

    calls: list[dict[str, object]] = []

    class FakeModel:
        def transcribe(self, path: str, **kwargs):
            calls.append(kwargs)
            return iter([]), SimpleNamespace(language="en", language_probability=0.995, duration=20.0, duration_after_vad=19.98)

    service._transcribe_windowed_timeline(
        audio_path,
        total_duration=70.0,
        started_at=0.0,
        cleanup_eta_seconds=300,
        on_stage=None,
        preserve_fillers=False,
        window_seconds=20.0,
        overlap_seconds=2.0,
        language_override="auto",
    )

    assert len(calls) >= 3
    assert "language" not in calls[0]
    assert calls[0]["vad_filter"] is True
    assert calls[1]["language"] == "en"
    assert calls[2]["vad_filter"] is False


def test_generate_caption_file_dedupes_overlapping_duplicate_lines(monkeypatch, tmp_path: Path):
    sample_rate = 16000
    audio = np.zeros(int(sample_rate * 3.5), dtype=np.float32)
    audio_path = tmp_path / "lecture.wav"
    _write_test_wav(audio_path, audio, sample_rate=sample_rate)

    service = SpeechCleanupService()
    monkeypatch.setattr(service, "capability_status", lambda: (True, "ready"))
    monkeypatch.setattr("radcast.services.speech_cleanup.run_ffmpeg_convert", lambda src, dst: shutil.copy2(src, dst))
    monkeypatch.setattr(
        service,
        "_transcribe_timeline",
        lambda *args, **kwargs: (
            [],
            [
                TranscriptSegmentTiming(text="Kia ora and welcome everyone", start=0.0, end=1.8, average_probability=0.84),
                TranscriptSegmentTiming(text="Kia ora and welcome everyone", start=1.62, end=2.08, average_probability=0.79),
                TranscriptSegmentTiming(text="We will start with tikanga.", start=2.15, end=3.2, average_probability=0.88),
            ],
        ),
    )

    result = service.generate_caption_file(audio_path=audio_path, caption_format=CaptionFormat.VTT)

    assert result.segment_count == 2
    text = result.caption_path.read_text(encoding="utf-8")
    assert text.count("Kia ora and welcome everyone") == 1
    assert "We will start with tikanga." in text


def test_format_caption_document_wraps_long_line_into_two_readable_lines():
    segments = [
        TranscriptSegmentTiming(
            text="This sentence should wrap near a comma, rather than becoming one long caption line.",
            start=0.0,
            end=4.2,
            average_probability=0.91,
        )
    ]

    text = _format_caption_document(segments, caption_format=CaptionFormat.VTT)

    assert "This sentence should wrap near a comma,\nrather than becoming one long caption line." in text


def test_clean_caption_text_normalizes_hyphen_spaced_compounds():
    assert _clean_caption_text("step -by -step methodology") == "step-by-step methodology"


def test_clean_caption_text_dedupes_accidental_repeated_first_word():
    assert _clean_caption_text("If If that apparent inconsistency is found") == "If that apparent inconsistency is found"


def test_clean_caption_text_joins_in_this_case_fragment_to_following_clause():
    assert (
        _clean_caption_text("In this case, it touches upon the presumption to be found, the presumption of innocence")
        == "In this case, it touches upon the presumption of innocence"
    )


def test_clean_caption_text_removes_bad_it_is_the_join():
    assert (
        _clean_caption_text("it is The apparent inconsistency at step 2 is legitimised and Parliament's")
        == "The apparent inconsistency at step 2 is legitimised and Parliament's"
    )


def test_clean_caption_text_removes_bad_it_is_the_join_mid_sentence():
    assert (
        _clean_caption_text(
            "is a justified limit, and you have made that argument, it is The apparent inconsistency at step 2 is legitimised"
        )
        == "is a justified limit, and you have made that argument, The apparent inconsistency at step 2 is legitimised"
    )


def test_clean_caption_text_fixes_step_two_ascertain_phrase():
    assert (
        _clean_caption_text(
            "If that apparent inconsistency that is found at Step 2 ascertain whether that inconsistency is nevertheless justified."
        )
        == "If that apparent inconsistency is found at Step 2, ascertain whether that inconsistency is nevertheless justified."
    )


def test_clean_caption_text_simplifies_step_four_transition_phrase():
    assert (
        _clean_caption_text(
            "Now, if it is justified, and so this is moving to step 4, if the inconsistency is a justified limit"
        )
        == "Now, moving to step 4, if the inconsistency is a justified limit"
    )


def test_format_caption_document_normalizes_transcript_artifacts_before_render():
    segments = [
        TranscriptSegmentTiming(
            text="is he sets out a step -by -step methodology for approaching any inconsistency with NZBORA.",
            start=0.0,
            end=5.0,
            average_probability=0.88,
        ),
        TranscriptSegmentTiming(
            text="If If that apparent inconsistency that is found at Step 2 ascertain whether it is justified.",
            start=5.1,
            end=10.2,
            average_probability=0.84,
        ),
    ]

    text = _format_caption_document(segments, caption_format=CaptionFormat.VTT)

    assert "step-by-step" in text
    assert "If If" not in text


def test_dedupe_adjacent_caption_blocks_trims_boundary_overlap_only():
    segments = [
        TranscriptSegmentTiming(text="This section explains accessible", start=0.0, end=1.8, average_probability=0.9),
        TranscriptSegmentTiming(text="accessible captions for learners", start=1.8, end=3.4, average_probability=0.9),
    ]

    deduped = _dedupe_adjacent_caption_blocks(segments)

    assert deduped[0].text == "This section explains accessible"
    assert deduped[1].text == "captions for learners"


def test_compose_accessible_caption_blocks_merges_connector_fragment_with_previous_cue():
    segments = [
        TranscriptSegmentTiming(
            text="In a tikanga Māori space, the victim has a very important role in the process of utu,",
            start=0.88,
            end=8.32,
            average_probability=0.91,
        ),
        TranscriptSegmentTiming(
            text="or the process of rebalancing.",
            start=8.42,
            end=10.02,
            average_probability=0.91,
        ),
    ]

    composed = _compose_accessible_caption_blocks(segments)

    rendered_text = " ".join(segment.text.replace("\n", " ") for segment in composed)

    assert rendered_text == (
        "In a tikanga Māori space, the victim has a very important role in the process of utu, "
        "or the process of rebalancing."
    )
    assert all(not segment.text.startswith("or ") for segment in composed)


def test_compose_accessible_caption_blocks_merges_short_leadin_with_following_clause():
    segments = [
        TranscriptSegmentTiming(text="So coming to", start=26.32, end=27.5, average_probability=0.93),
        TranscriptSegmentTiming(
            text="an agreement as to how it is best to rehabilitate and rebalance the harm",
            start=27.5,
            end=38.1,
            average_probability=0.93,
        ),
        TranscriptSegmentTiming(text="that was done.", start=38.1, end=38.78, average_probability=0.93),
    ]

    composed = _compose_accessible_caption_blocks(segments)

    rendered_text = " ".join(segment.text.replace("\n", " ") for segment in composed)

    assert rendered_text == (
        "So coming to an agreement as to how it is best to rehabilitate and rebalance the harm "
        "that was done."
    )
    assert all(segment.text != "So coming to" for segment in composed)
    assert all(segment.text != "that was done." for segment in composed)


def test_compose_accessible_caption_blocks_avoids_dangling_trailing_line_fragments():
    segments = [
        TranscriptSegmentTiming(
            text=(
                "In a tikanga Māori space, the victim has a very important role in the process of utu, "
                "or the process of rebalancing."
            ),
            start=0.88,
            end=10.02,
            average_probability=0.91,
        ),
        TranscriptSegmentTiming(
            text=(
                "there is a… collective involvement of the victim and the community with both the perpetrator "
                "and the perpetrator's community in rebalancing and restoring balance."
            ),
            start=13.94,
            end=26.32,
            average_probability=0.92,
        ),
        TranscriptSegmentTiming(
            text=(
                "So coming to an agreement as to how it is best to rehabilitate and rebalance "
                "the harm that was done."
            ),
            start=26.32,
            end=38.78,
            average_probability=0.93,
        ),
    ]

    composed = _compose_accessible_caption_blocks(segments)

    lines = [
        line.strip()
        for segment in composed
        for line in segment.text.splitlines()
        if line.strip()
    ]
    trailing_words = {line.split()[-1].lower() for line in lines}

    assert "the" not in trailing_words
    assert "with" not in trailing_words
    assert "that" not in trailing_words
    assert "in" not in trailing_words
    assert all(segment.text != "was done." for segment in composed)
    assert all(segment.text != "both the perpetrator" for segment in composed)
    assert all(segment.text != "there is a… collective" for segment in composed)


def test_compose_accessible_caption_blocks_does_not_merge_new_sentence_into_previous_period():
    segments = [
        TranscriptSegmentTiming(
            text="the perpetrator's community in rebalancing and restoring balance.",
            start=21.68,
            end=26.26,
            average_probability=0.92,
        ),
        TranscriptSegmentTiming(
            text="So coming to an agreement as to how it is best to rehabilitate and rebalance the harm that was done.",
            start=26.32,
            end=38.78,
            average_probability=0.93,
        ),
    ]

    composed = _compose_accessible_caption_blocks(segments)

    assert all("balance.\nSo coming" not in segment.text for segment in composed)
    rendered_text = " ".join(segment.text.replace("\n", " ") for segment in composed)
    assert "balance. So coming" in rendered_text


def test_compose_accessible_caption_blocks_rebalances_continuation_starts():
    segments = [
        TranscriptSegmentTiming(
            text="there is a… collective involvement of the victim and the community",
            start=13.949,
            end=20.381,
            average_probability=0.92,
        ),
        TranscriptSegmentTiming(
            text="with both the perpetrator",
            start=20.381,
            end=22.720,
            average_probability=0.92,
        ),
        TranscriptSegmentTiming(
            text="and the perpetrator's community in rebalancing and restoring balance.",
            start=22.720,
            end=26.320,
            average_probability=0.92,
        ),
        TranscriptSegmentTiming(
            text="So coming to an agreement as to how it is best to rehabilitate",
            start=26.320,
            end=34.419,
            average_probability=0.93,
        ),
        TranscriptSegmentTiming(
            text="and rebalance the harm that was done.",
            start=34.419,
            end=38.780,
            average_probability=0.93,
        ),
    ]

    composed = _compose_accessible_caption_blocks(segments)
    texts = [segment.text.replace("\n", " ") for segment in composed]

    assert all(not text.startswith("with ") for text in texts)
    assert all(not text.startswith("and ") for text in texts)


def test_compose_accessible_caption_blocks_merges_numeric_stub_cue():
    segments = [
        TranscriptSegmentTiming(
            text="five, which is if Parliament's intended meaning represents an unjustified limit under section",
            start=39.40,
            end=40.82,
            average_probability=0.92,
        ),
        TranscriptSegmentTiming(text="5.", start=40.82, end=41.02, average_probability=0.92),
        TranscriptSegmentTiming(
            text="The court must examine So only now, after that Section 5 analysis, do we move on.",
            start=41.02,
            end=49.48,
            average_probability=0.92,
        ),
    ]

    composed = _compose_accessible_caption_blocks(segments)
    texts = [segment.text.replace("\n", " ") for segment in composed]

    assert all(text != "5." for text in texts)
    assert any("section 5." in text.lower() for text in texts)


def test_compose_accessible_caption_blocks_keeps_step_transition_with_legal_sentence():
    segments = [
        TranscriptSegmentTiming(
            text="against any adverse sort of depiction.",
            start=48.92,
            end=51.51,
            average_probability=0.9,
        ),
        TranscriptSegmentTiming(
            text="of that. Step 2 is ascertain whether that meaning is apparently",
            start=52.62,
            end=58.28,
            average_probability=0.88,
        ),
        TranscriptSegmentTiming(
            text="inconsistent with a relevant right or freedom.",
            start=58.28,
            end=61.88,
            average_probability=0.9,
        ),
    ]

    composed = _compose_accessible_caption_blocks(segments)
    texts = [segment.text.replace("\n", " ") for segment in composed]

    assert all(not text.startswith("of that.") for text in texts)
    assert any("Step 2" in text and "ascertain" in text for text in texts)


def test_compose_accessible_caption_blocks_merges_justified_tail_fragment():
    segments = [
        TranscriptSegmentTiming(
            text="society, or it is justified.",
            start=169.95,
            end=172.30,
            average_probability=0.9,
        ),
        TranscriptSegmentTiming(
            text="is now justified. The apparent inconsistency at step 2 is legitimised and Parliament's",
            start=181.37,
            end=187.02,
            average_probability=0.88,
        ),
        TranscriptSegmentTiming(
            text="intended meaning prevails.",
            start=187.02,
            end=188.39,
            average_probability=0.9,
        ),
    ]

    composed = _compose_accessible_caption_blocks(segments)
    texts = [segment.text.replace("\n", " ") for segment in composed]

    assert all(not text.startswith("is now justified.") for text in texts)
    assert any("The apparent inconsistency at step 2 is legitimised" in text for text in texts)


def test_format_caption_document_cleans_remaining_legal_phrase_artifacts():
    segments = [
        TranscriptSegmentTiming(
            text="In this case, it",
            start=84.40,
            end=86.42,
            average_probability=0.9,
        ),
        TranscriptSegmentTiming(
            text="touches upon the presumption to be found, the presumption of innocence",
            start=86.42,
            end=91.98,
            average_probability=0.88,
        ),
        TranscriptSegmentTiming(
            text="until found guilty.",
            start=91.98,
            end=93.49,
            average_probability=0.9,
        ),
        TranscriptSegmentTiming(
            text="it is The apparent inconsistency at step 2 is legitimised and Parliament's",
            start=181.55,
            end=187.15,
            average_probability=0.88,
        ),
        TranscriptSegmentTiming(
            text="intended meaning prevails.",
            start=187.15,
            end=188.58,
            average_probability=0.9,
        ),
    ]

    text = _format_caption_document(segments, caption_format=CaptionFormat.VTT)

    assert "presumption to be found" not in text
    assert "In this case, it touches upon the presumption" in text
    assert "of innocence until found guilty." in text
    assert "it is The apparent inconsistency" not in text
    assert "The apparent inconsistency at step" in text
    assert "2 is legitimised and Parliament's" in text


def test_format_caption_document_cleans_remaining_hansen_step_phrases():
    segments = [
        TranscriptSegmentTiming(
            text="If that apparent inconsistency that is found at Step 2 ascertain",
            start=103.91,
            end=109.22,
            average_probability=0.88,
        ),
        TranscriptSegmentTiming(
            text="whether that inconsistency is nevertheless justified in terms of section 5.",
            start=109.22,
            end=114.51,
            average_probability=0.9,
        ),
        TranscriptSegmentTiming(
            text="Now, if it is justified, and so this is moving to step 4, if the inconsistency",
            start=172.86,
            end=177.73,
            average_probability=0.88,
        ),
        TranscriptSegmentTiming(
            text="is a justified limit, and you have made that argument.",
            start=177.73,
            end=183.20,
            average_probability=0.9,
        ),
    ]

    text = _format_caption_document(segments, caption_format=CaptionFormat.VTT)

    assert "that is found at Step 2 ascertain" not in text
    assert "is found at Step 2," in text
    assert "ascertain whether that inconsistency" in text
    assert "and so this is moving to step 4" not in text
    assert "Now, moving to step 4" in text


def test_format_caption_document_removes_embedded_it_is_the_join():
    segments = [
        TranscriptSegmentTiming(
            text="Now, moving to step 4, if the inconsistency is a justified limit, and you have made that argument,",
            start=172.86,
            end=180.52,
            average_probability=0.9,
        ),
        TranscriptSegmentTiming(
            text="it is The apparent inconsistency at step 2 is legitimised and Parliament's",
            start=180.52,
            end=186.15,
            average_probability=0.88,
        ),
        TranscriptSegmentTiming(
            text="intended meaning prevails.",
            start=186.15,
            end=187.58,
            average_probability=0.9,
        ),
    ]

    text = _format_caption_document(segments, caption_format=CaptionFormat.VTT)

    assert "it is The apparent" not in text
    assert ", The" in text
    assert "inconsistency at step 2 is" in text


def test_build_caption_prompt_includes_nz_legal_terms():
    prompt = _build_caption_prompt(None)

    assert "NZBORA" in prompt
    assert "Tipping J" in prompt
    assert "Moonen" in prompt


def test_generate_caption_file_reviewed_mode_uses_review_sweep_and_custom_glossary(monkeypatch, tmp_path: Path):
    sample_rate = 16000
    audio = np.zeros(int(sample_rate * 1.5), dtype=np.float32)
    audio_path = tmp_path / "lecture.wav"
    _write_test_wav(audio_path, audio, sample_rate=sample_rate)

    service = SpeechCleanupService()
    monkeypatch.setattr(service, "capability_status", lambda: (True, "ready"))
    monkeypatch.setattr("radcast.services.speech_cleanup.run_ffmpeg_convert", lambda src, dst: shutil.copy2(src, dst))

    captured: dict[str, object] = {}

    def fake_transcribe_timeline(*args, **kwargs):
        captured.update(kwargs)
        return [], [
            TranscriptSegmentTiming(
                text="Organisation and tikanga need careful review here",
                start=0.0,
                end=1.1,
                average_probability=0.35,
            )
        ]

    def fake_review_and_correct_caption_segments(**kwargs):
        captured["review_called"] = True
        captured["review_prompt"] = kwargs.get("prompt_text")
        return [
            TranscriptSegmentTiming(
                text="Organisation and tikanga Māori need careful review here",
                start=0.0,
                end=1.1,
                average_probability=0.86,
            )
        ]

    monkeypatch.setattr(service, "_transcribe_timeline", fake_transcribe_timeline)
    monkeypatch.setattr(service, "_review_and_correct_caption_segments", fake_review_and_correct_caption_segments)

    result = service.generate_caption_file(
        audio_path=audio_path,
        caption_format=CaptionFormat.VTT,
        caption_quality_mode=CaptionQualityMode.REVIEWED,
        caption_glossary="Te Tiriti o Waitangi, kaiwhakahaere",
    )

    assert result.quality_report is not None
    assert captured["model_size"] == service.caption_accurate_model_size
    assert captured["beam_size"] == service.caption_accurate_beam_size
    assert captured["condition_on_previous_text"] is True
    assert captured["window_seconds"] == 24.0
    assert captured["overlap_seconds"] == 2.5
    assert captured["review_called"] is True
    assert "organisation" in str(captured["initial_prompt"])
    assert "Te Tiriti o Waitangi" in str(captured["initial_prompt"])
    assert "kaiwhakahaere" in str(captured["review_prompt"])


def test_generate_caption_file_writes_review_notes_for_low_confidence_segments(monkeypatch, tmp_path: Path):
    sample_rate = 16000
    audio = np.zeros(int(sample_rate * 1.5), dtype=np.float32)
    audio_path = tmp_path / "lecture.wav"
    _write_test_wav(audio_path, audio, sample_rate=sample_rate)

    service = SpeechCleanupService()
    monkeypatch.setattr(service, "capability_status", lambda: (True, "ready"))
    monkeypatch.setattr("radcast.services.speech_cleanup.run_ffmpeg_convert", lambda src, dst: shutil.copy2(src, dst))
    monkeypatch.setattr(
        service,
        "_transcribe_timeline",
        lambda *args, **kwargs: (
            [],
            [
                TranscriptSegmentTiming(text="This line should be checked", start=0.0, end=1.4, average_probability=0.31),
                TranscriptSegmentTiming(text="This line is okay", start=1.6, end=2.2, average_probability=0.83),
            ],
        ),
    )

    result = service.generate_caption_file(audio_path=audio_path, caption_format=CaptionFormat.VTT)

    assert result.review_path is not None
    assert result.review_path.exists()
    assert result.quality_report is not None
    assert result.quality_report.review_recommended is True
    assert result.quality_report.low_confidence_segment_count == 1
    review_text = result.review_path.read_text(encoding="utf-8")
    assert "low-confidence" in review_text.lower()
    assert "This line should be checked" in review_text


def test_estimate_caption_runtime_seconds_adds_cold_start_for_uncached_accurate_model(monkeypatch):
    service = SpeechCleanupService()
    monkeypatch.setattr(service, "_model_cache_ready", lambda model_size: False)

    cold_seconds = service.estimate_caption_runtime_seconds(120, quality_mode=CaptionQualityMode.ACCURATE)

    monkeypatch.setattr(service, "_model_cache_ready", lambda model_size: True)
    warm_seconds = service.estimate_caption_runtime_seconds(120, quality_mode=CaptionQualityMode.ACCURATE)

    assert cold_seconds > warm_seconds


def test_caption_accurate_model_defaults_to_large_v3_turbo():
    service = SpeechCleanupService()

    assert service.caption_accurate_model_size == "large-v3-turbo"


def test_estimate_caption_runtime_seconds_for_reviewed_mode_accounts_for_review_model_cache(monkeypatch):
    service = SpeechCleanupService()
    monkeypatch.setattr(
        service,
        "_model_cache_ready",
        lambda model_size: model_size != service.caption_reviewed_model_size,
    )

    cold_seconds = service.estimate_caption_runtime_seconds(120, quality_mode=CaptionQualityMode.REVIEWED)

    monkeypatch.setattr(service, "_model_cache_ready", lambda model_size: True)
    warm_seconds = service.estimate_caption_runtime_seconds(120, quality_mode=CaptionQualityMode.REVIEWED)

    assert cold_seconds > warm_seconds


def test_transcription_eta_stays_conservative_until_late_caption_stage():
    assert _transcription_eta_seconds(elapsed_seconds=65, cleanup_eta_seconds=95, coverage=0.86) >= 15
    assert _transcription_eta_seconds(elapsed_seconds=88, cleanup_eta_seconds=95, coverage=0.95) >= 5


def test_windowed_transcription_eta_stays_conservative_across_tail():
    assert _windowed_transcription_eta_seconds(
        elapsed_seconds=70,
        cleanup_eta_seconds=140,
        processed_windows=6,
        total_windows=12,
        coverage=0.52,
    ) >= 40
    assert _windowed_transcription_eta_seconds(
        elapsed_seconds=118,
        cleanup_eta_seconds=140,
        processed_windows=11,
        total_windows=12,
        coverage=0.94,
    ) >= 8


def test_windowed_transcription_eta_does_not_explode_from_one_slow_early_window():
    eta = _windowed_transcription_eta_seconds(
        elapsed_seconds=300,
        cleanup_eta_seconds=900,
        processed_windows=1,
        total_windows=8,
        coverage=0.13,
    )

    assert eta <= 1500


def test_review_budget_shrinks_for_long_reviewed_caption_jobs():
    assert _caption_review_flag_budget(90) >= _caption_review_flag_budget(300)
    assert _caption_review_flag_budget(300) >= _caption_review_flag_budget(900)
    assert _caption_review_flag_budget(900) <= 4


def test_generate_caption_file_seeds_window_detail_before_first_window_finishes(monkeypatch, tmp_path: Path):
    sample_rate = 16000
    audio = np.zeros(int(sample_rate * 65.0), dtype=np.float32)
    audio_path = tmp_path / "lecture.wav"
    _write_test_wav(audio_path, audio, sample_rate=sample_rate)

    service = SpeechCleanupService()
    monkeypatch.setattr(service, "capability_status", lambda: (True, "ready"))
    monkeypatch.setattr("radcast.services.speech_cleanup.run_ffmpeg_convert", lambda src, dst: shutil.copy2(src, dst))

    progress_updates: list[tuple[float, str, int | None]] = []

    def fake_transcribe_timeline(*args, **kwargs):
        return [], [TranscriptSegmentTiming(text="Caption text", start=0.0, end=1.0)]

    monkeypatch.setattr(service, "_transcribe_timeline", fake_transcribe_timeline)

    service.generate_caption_file(
        audio_path=audio_path,
        caption_format=CaptionFormat.VTT,
        caption_quality_mode=CaptionQualityMode.REVIEWED,
        on_stage=lambda progress, detail, eta: progress_updates.append((progress, detail, eta)),
    )

    assert progress_updates
    initial_detail = progress_updates[0][1]
    assert "Window 1 of" in initial_detail


def test_generate_caption_file_emits_post_transcription_analysis_and_formatting_stages(monkeypatch, tmp_path: Path):
    sample_rate = 16000
    audio = np.zeros(int(sample_rate * 90.0), dtype=np.float32)
    audio_path = tmp_path / "lecture.wav"
    _write_test_wav(audio_path, audio, sample_rate=sample_rate)

    service = SpeechCleanupService()
    monkeypatch.setattr(service, "capability_status", lambda: (True, "ready"))
    monkeypatch.setattr("radcast.services.speech_cleanup.run_ffmpeg_convert", lambda src, dst: shutil.copy2(src, dst))
    monkeypatch.setattr(
        service,
        "_transcribe_timeline",
        lambda *args, **kwargs: (
            [],
            [TranscriptSegmentTiming(text="Caption text", start=0.0, end=1.0, average_probability=0.95)],
        ),
    )

    progress_updates: list[tuple[float, str, int | None]] = []

    service.generate_caption_file(
        audio_path=audio_path,
        caption_format=CaptionFormat.VTT,
        caption_quality_mode=CaptionQualityMode.REVIEWED,
        on_stage=lambda progress, detail, eta: progress_updates.append((progress, detail, eta)),
    )

    details = [detail for _, detail, _ in progress_updates]
    assert any("Analyzing caption confidence." in detail for detail in details)
    assert any("Formatting accessible captions." in detail for detail in details)


def test_cleanup_audio_file_removes_adjacent_filler_pair_as_single_hesitation(monkeypatch, tmp_path: Path):
    sample_rate = 16000
    tone_t = np.linspace(0.0, 0.28, int(sample_rate * 0.28), endpoint=False)
    speech_a = 0.18 * np.sin(2.0 * np.pi * 220.0 * tone_t)
    speech_b = 0.18 * np.sin(2.0 * np.pi * 310.0 * tone_t)
    filler_t = np.linspace(0.0, 0.12, int(sample_rate * 0.12), endpoint=False)
    filler_a = 0.1 * np.sin(2.0 * np.pi * 170.0 * filler_t)
    filler_b = 0.1 * np.sin(2.0 * np.pi * 160.0 * filler_t)
    gap_a = np.zeros(int(sample_rate * 0.05), dtype=np.float32)
    gap_mid = np.zeros(int(sample_rate * 0.04), dtype=np.float32)
    gap_b = np.zeros(int(sample_rate * 0.06), dtype=np.float32)
    audio = np.concatenate([speech_a, gap_a, filler_a, gap_mid, filler_b, gap_b, speech_b]).astype(np.float32)
    audio_path = tmp_path / "lecture.wav"
    _write_test_wav(audio_path, audio, sample_rate=sample_rate)
    original_duration = _wav_duration_seconds(audio_path)

    service = SpeechCleanupService()
    monkeypatch.setattr(service, "capability_status", lambda: (True, "ready"))
    monkeypatch.setattr(
        service,
        "_transcribe_timeline",
        lambda _path, **kwargs: (
            [
                TranscriptWordTiming(text="right", start=0.0, end=0.28, probability=0.94),
                TranscriptWordTiming(text="um", start=0.33, end=0.45, probability=0.28),
                TranscriptWordTiming(text="uh", start=0.49, end=0.61, probability=0.26),
                TranscriptWordTiming(text="then", start=0.67, end=0.95, probability=0.92),
            ],
            [],
        ),
    )
    monkeypatch.setattr("radcast.services.speech_cleanup.run_ffmpeg_convert", lambda src, dst, *, audio_filters=None: shutil.copy2(src, dst))
    monkeypatch.setattr("radcast.services.speech_cleanup.probe_duration_seconds", _wav_duration_seconds)

    result = service.cleanup_audio_file(
        audio_path=audio_path,
        output_format=OutputFormat.WAV,
        max_silence_seconds=None,
        remove_filler_words=True,
    )

    assert result.applied is True
    assert result.removed_filler_count == 2
    assert result.duration_seconds < original_duration


def test_cleanup_result_summary_text_formats_counts():
    result = SpeechCleanupResult(applied=True, removed_pause_count=2, removed_filler_count=1, duration_seconds=9.5)

    assert result.summary_text() == "Shortened 2 long pauses, removed 1 filler word."
