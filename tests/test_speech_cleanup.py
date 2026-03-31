from __future__ import annotations

import sys
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

    def fake_transcribe_file(
        _model,
        clip_path: Path,
        *,
        preserve_fillers: bool,
        beam_size: int | None = None,
        condition_on_previous_text: bool = False,
        initial_prompt: str | None = None,
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
            ]
        if clip_path.name == "window_006000.wav":
            return [
                SimpleNamespace(
                    start=1.1,
                    end=1.34,
                    text="uh",
                    words=[SimpleNamespace(start=1.1, end=1.34, word="uh", probability=0.01)],
                )
            ]
        return []

    monkeypatch.setattr(service, "_transcribe_file", fake_transcribe_file)

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
    assert captured["window_seconds"] == 16.0
    assert captured["overlap_seconds"] == 3.0
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
                TranscriptSegmentTiming(text="This line should be checked", start=0.0, end=1.4, average_probability=0.39),
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


def test_load_model_evicts_other_cached_models(monkeypatch):
    service = SpeechCleanupService()

    class FakeWhisperModel:
        def __init__(self, model_size: str, device: str | None = None, compute_type: str | None = None):
            self.model_size = model_size
            self.device = device
            self.compute_type = compute_type

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisperModel))

    medium_model = service._load_model("medium")
    assert service._models.keys() == {"medium"}

    large_model = service._load_model("large-v3")
    assert service._models.keys() == {"large-v3"}
    assert medium_model is not large_model
    assert service._load_model("large-v3") is large_model


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
