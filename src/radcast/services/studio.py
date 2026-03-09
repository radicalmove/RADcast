"""Custom single-channel dereverb used by the Studio Cleanup backend."""

from __future__ import annotations

import math

import numpy as np
from scipy.linalg import solve
from scipy.signal import istft, stft


def suppress_late_reverb(
    audio: np.ndarray,
    sample_rate: int,
    *,
    fft_size: int | None = None,
    hop_size: int | None = None,
    delay_ms: float = 20.0,
    decay_ms: float = 180.0,
    reduction: float = 0.72,
    gain_floor: float = 0.16,
    time_smoothing: float = 0.72,
    transient_threshold: float = 1.45,
    transient_floor: float = 0.9,
) -> np.ndarray:
    """Suppress late reverberation with a delayed spectral tail estimate.

    This is intentionally conservative. The goal is not perfect dereverberation;
    it is to trim room tail before the enhancement model reconstructs speech.
    """

    if audio.ndim != 1:
        raise ValueError("audio must be mono")

    if len(audio) < 256:
        return audio.astype(np.float32, copy=False)

    n_fft = int(fft_size or (1024 if sample_rate >= 32000 else 512))
    hop = int(hop_size or max(128, n_fft // 4))
    noverlap = n_fft - hop
    if noverlap <= 0:
        raise ValueError("hop_size must be smaller than fft_size")

    _freqs, _times, spec = stft(
        audio,
        fs=sample_rate,
        nperseg=n_fft,
        noverlap=noverlap,
        boundary="zeros",
        padded=True,
    )
    power = np.abs(spec) ** 2
    if power.shape[1] < 2:
        return audio.astype(np.float32, copy=False)

    delay_frames = max(1, int(round((delay_ms / 1000.0) * sample_rate / hop)))
    decay_frames = max(2, int(round((decay_ms / 1000.0) * sample_rate / hop)))
    alpha = math.exp(-1.0 / float(decay_frames))

    late = np.zeros_like(power)
    for frame_index in range(1, power.shape[1]):
        source_index = max(0, frame_index - delay_frames)
        late[:, frame_index] = (alpha * late[:, frame_index - 1]) + ((1.0 - alpha) * power[:, source_index])

    # Smooth the late-tail estimate across neighbouring frequency bins to reduce musical noise.
    smoothed_late = late.copy()
    smoothed_late[1:-1] = (late[:-2] + (2.0 * late[1:-1]) + late[2:]) / 4.0
    late = smoothed_late

    eps = 1e-10
    direct_power = np.maximum(power - (reduction * late), gain_floor * power)
    gain = np.sqrt(np.clip(direct_power / np.maximum(power, eps), gain_floor, 1.0))

    for frame_index in range(1, gain.shape[1]):
        gain[:, frame_index] = (time_smoothing * gain[:, frame_index - 1]) + (
            (1.0 - time_smoothing) * gain[:, frame_index]
        )

    transients = power > (transient_threshold * (late + eps))
    gain = np.where(transients, np.maximum(gain, transient_floor), gain)

    processed_spec = spec * gain
    _times, processed = istft(
        processed_spec,
        fs=sample_rate,
        nperseg=n_fft,
        noverlap=noverlap,
        input_onesided=True,
    )

    processed = processed[: len(audio)]
    peak = float(np.max(np.abs(processed))) if processed.size else 0.0
    if peak > 0.999:
        processed = processed / peak * 0.999
    return processed.astype(np.float32, copy=False)


def wpe_dereverb(
    audio: np.ndarray,
    sample_rate: int,
    *,
    fft_size: int | None = None,
    hop_size: int | None = None,
    taps: int = 10,
    delay: int = 3,
    iterations: int = 2,
    regularization: float = 1e-4,
) -> np.ndarray:
    """Single-channel WPE-style dereverberation.

    This is still an approximation, but it targets late reverberation more
    directly than the simple spectral-tail suppressor above.
    """

    if audio.ndim != 1:
        raise ValueError("audio must be mono")
    if len(audio) < 256:
        return audio.astype(np.float32, copy=False)

    n_fft = int(fft_size or (1024 if sample_rate >= 32000 else 512))
    hop = int(hop_size or max(128, n_fft // 4))
    noverlap = n_fft - hop
    if noverlap <= 0:
        raise ValueError("hop_size must be smaller than fft_size")

    _freqs, _times, spec = stft(
        audio,
        fs=sample_rate,
        nperseg=n_fft,
        noverlap=noverlap,
        boundary="zeros",
        padded=True,
    )
    if spec.shape[1] <= (delay + taps + 2):
        return audio.astype(np.float32, copy=False)

    observed = spec.copy()
    estimate = spec.copy()
    start_frame = delay + taps
    feature_count = taps

    for _ in range(max(1, iterations)):
        power = np.maximum(np.abs(estimate) ** 2, 1e-8)
        time_variance = np.maximum(np.mean(power, axis=0), 1e-8)
        updated = observed.copy()
        for bin_index in range(observed.shape[0]):
            y = observed[bin_index]
            target = y[start_frame:]
            if target.size == 0:
                continue

            history = np.empty((feature_count, target.size), dtype=np.complex128)
            for tap_index in range(feature_count):
                history[tap_index] = y[start_frame - delay - tap_index : -delay - tap_index]

            weights = 1.0 / np.maximum(time_variance[start_frame:], 1e-8)
            weighted_history = history * weights[np.newaxis, :]
            correlation = weighted_history @ history.conj().T
            correlation += np.eye(feature_count, dtype=np.complex128) * regularization
            projection = weighted_history @ target.conj()

            coeffs = solve(correlation, projection, assume_a="her")
            prediction = coeffs.conj() @ history
            updated[bin_index, start_frame:] = target - prediction
        estimate = updated

    _times, processed = istft(
        estimate,
        fs=sample_rate,
        nperseg=n_fft,
        noverlap=noverlap,
        input_onesided=True,
    )
    processed = processed[: len(audio)]
    peak = float(np.max(np.abs(processed))) if processed.size else 0.0
    if peak > 0.999:
        processed = processed / peak * 0.999
    return processed.astype(np.float32, copy=False)
