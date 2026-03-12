"""Progress helpers for enhancement and speech cleanup stages."""

from __future__ import annotations


def estimate_speech_cleanup_seconds(duration_seconds: float | None, *, remove_filler_words: bool) -> int:
    safe_duration = max(1.0, float(duration_seconds or 1.0))
    base_seconds = 8.0 if remove_filler_words else 6.0
    per_second = 0.26 if remove_filler_words else 0.18
    return max(6, min(int(round(base_seconds + (safe_duration * per_second))), 12 * 60))


def map_local_stage_progress(stage: str, progress: float, *, reserve_cleanup_band: bool) -> float:
    normalized = str(stage or "").strip().lower()
    clamped = max(0.0, min(1.0, float(progress)))
    if not reserve_cleanup_band:
        return clamped
    if normalized == "prepare":
        return _remap(clamped, source_start=0.08, source_end=0.22, target_start=0.08, target_end=0.16)
    if normalized == "enhance":
        return _remap(clamped, source_start=0.2, source_end=0.88, target_start=0.16, target_end=0.68)
    if normalized == "finalize":
        return _remap(clamped, source_start=0.9, source_end=0.96, target_start=0.68, target_end=0.72)
    return clamped


def map_worker_stage_progress(stage: str, progress: float, *, reserve_cleanup_band: bool) -> float:
    normalized = str(stage or "").strip().lower()
    clamped = max(0.0, min(1.0, float(progress)))
    if not reserve_cleanup_band:
        if normalized == "prepare":
            return min(0.22, max(0.14, clamped))
        if normalized == "enhance":
            return min(0.88, max(0.24, clamped))
        if normalized == "finalize":
            return min(0.96, max(0.9, clamped))
        return clamped
    if normalized == "prepare":
        return _remap(clamped, source_start=0.08, source_end=0.22, target_start=0.14, target_end=0.18)
    if normalized == "enhance":
        return _remap(clamped, source_start=0.2, source_end=0.88, target_start=0.18, target_end=0.68)
    if normalized == "finalize":
        return _remap(clamped, source_start=0.9, source_end=0.96, target_start=0.68, target_end=0.72)
    return clamped


def map_cleanup_stage_progress(progress: float) -> float:
    clamped = max(0.0, min(1.0, float(progress)))
    return _remap(clamped, source_start=0.0, source_end=1.0, target_start=0.72, target_end=0.96)


def extend_eta_with_cleanup(eta_seconds: int | None, cleanup_eta_seconds: int | None, *, reserve_cleanup_band: bool) -> int | None:
    if not reserve_cleanup_band or cleanup_eta_seconds is None:
        return eta_seconds
    if eta_seconds is None:
        return None
    return max(eta_seconds + cleanup_eta_seconds, cleanup_eta_seconds)


def _remap(
    value: float,
    *,
    source_start: float,
    source_end: float,
    target_start: float,
    target_end: float,
) -> float:
    if source_end <= source_start:
        return target_end
    normalized = (value - source_start) / (source_end - source_start)
    bounded = max(0.0, min(1.0, normalized))
    return target_start + ((target_end - target_start) * bounded)
