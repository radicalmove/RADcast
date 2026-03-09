from __future__ import annotations

import numpy as np
from scipy.signal import fftconvolve

from radcast.services.studio import suppress_late_reverb, wpe_dereverb


def _synthetic_dry_signal(sample_rate: int) -> tuple[np.ndarray, list[int]]:
    duration_seconds = 1.8
    total_samples = int(sample_rate * duration_seconds)
    signal = np.zeros(total_samples, dtype=np.float32)
    onsets = [int(sample_rate * t) for t in (0.18, 0.72, 1.18)]
    burst_length = int(sample_rate * 0.07)
    window = np.hanning(burst_length).astype(np.float32)
    t = np.arange(burst_length, dtype=np.float32) / sample_rate
    voiced = (
        0.8 * np.sin(2 * np.pi * 180 * t)
        + 0.4 * np.sin(2 * np.pi * 420 * t)
        + 0.15 * np.sin(2 * np.pi * 2400 * t)
    ).astype(np.float32)
    burst = voiced * window
    for onset in onsets:
        signal[onset : onset + burst_length] += burst
    return signal, onsets


def _measure_window_rms(signal: np.ndarray, start: int, end: int) -> float:
    segment = signal[start:end]
    return float(np.sqrt(np.mean(segment * segment) + 1e-12))


def test_suppress_late_reverb_reduces_tail_energy_without_crushing_direct_sound():
    sample_rate = 16000
    dry, onsets = _synthetic_dry_signal(sample_rate)

    impulse_length = int(sample_rate * 0.22)
    tail = np.exp(-np.linspace(0.0, 4.8, impulse_length)).astype(np.float32)
    room_ir = np.concatenate(([1.0], 0.42 * tail[1:])).astype(np.float32)
    reverberant = fftconvolve(dry, room_ir, mode="full")[: len(dry)].astype(np.float32)
    processed = suppress_late_reverb(reverberant, sample_rate)

    reverberant_tail = 0.0
    processed_tail = 0.0
    reverberant_direct = 0.0
    processed_direct = 0.0
    for onset in onsets:
        reverberant_direct += _measure_window_rms(reverberant, onset, onset + int(sample_rate * 0.04))
        processed_direct += _measure_window_rms(processed, onset, onset + int(sample_rate * 0.04))
        reverberant_tail += _measure_window_rms(
            reverberant,
            onset + int(sample_rate * 0.12),
            onset + int(sample_rate * 0.26),
        )
        processed_tail += _measure_window_rms(
            processed,
            onset + int(sample_rate * 0.12),
            onset + int(sample_rate * 0.26),
        )

    assert processed_tail < (reverberant_tail * 0.82)
    assert (processed_direct / max(processed_tail, 1e-12)) > (
        (reverberant_direct / max(reverberant_tail, 1e-12)) * 1.5
    )


def test_wpe_dereverb_improves_direct_to_tail_ratio():
    sample_rate = 16000
    dry, onsets = _synthetic_dry_signal(sample_rate)

    impulse_length = int(sample_rate * 0.26)
    tail = np.exp(-np.linspace(0.0, 6.0, impulse_length)).astype(np.float32)
    room_ir = np.concatenate(([1.0], 0.55 * tail[1:])).astype(np.float32)
    reverberant = fftconvolve(dry, room_ir, mode="full")[: len(dry)].astype(np.float32)
    processed = wpe_dereverb(reverberant, sample_rate, taps=8, delay=2, iterations=2)

    reverberant_tail = 0.0
    processed_tail = 0.0
    reverberant_direct = 0.0
    processed_direct = 0.0
    for onset in onsets:
        reverberant_direct += _measure_window_rms(reverberant, onset, onset + int(sample_rate * 0.05))
        processed_direct += _measure_window_rms(processed, onset, onset + int(sample_rate * 0.05))
        reverberant_tail += _measure_window_rms(
            reverberant,
            onset + int(sample_rate * 0.10),
            onset + int(sample_rate * 0.24),
        )
        processed_tail += _measure_window_rms(
            processed,
            onset + int(sample_rate * 0.10),
            onset + int(sample_rate * 0.24),
        )

    assert processed_tail < (reverberant_tail * 0.75)
    assert (processed_direct / max(processed_tail, 1e-12)) > (
        (reverberant_direct / max(reverberant_tail, 1e-12)) * 1.8
    )
