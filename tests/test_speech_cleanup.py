from __future__ import annotations

import shutil
import wave
from pathlib import Path

import numpy as np

from radcast.models import FillerRemovalMode, OutputFormat
from radcast.services.speech_cleanup import (
    SpeechCleanupResult,
    SpeechCleanupService,
    TranscriptWordTiming,
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
                TranscriptWordTiming(text="ah", start=0.315, end=0.425, probability=0.19),
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
