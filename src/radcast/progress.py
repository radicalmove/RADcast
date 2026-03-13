"""Progress helpers for enhancement and speech cleanup stages."""

from __future__ import annotations

from radcast.models import FillerRemovalMode


def estimate_speech_cleanup_seconds(
    duration_seconds: float | None,
    *,
    remove_filler_words: bool,
    filler_removal_mode: FillerRemovalMode = FillerRemovalMode.AGGRESSIVE,
) -> int:
    safe_duration = max(1.0, float(duration_seconds or 1.0))
    if remove_filler_words:
        if filler_removal_mode == FillerRemovalMode.AGGRESSIVE:
            base_seconds = 18.0
            per_second = 0.55
        else:
            base_seconds = 11.0
            per_second = 0.32
    else:
        base_seconds = 7.0
        per_second = 0.22
    return max(6, min(int(round(base_seconds + (safe_duration * per_second))), 12 * 60))


def estimate_caption_seconds(duration_seconds: float | None) -> int:
    safe_duration = max(1.0, float(duration_seconds or 1.0))
    return max(12, min(int(round(14.0 + (safe_duration * 0.55))), 12 * 60))


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
    return map_postprocess_stage_progress(progress, stage="cleanup", cleanup_requested=True, caption_requested=False)


def extend_eta_with_cleanup(eta_seconds: int | None, cleanup_eta_seconds: int | None, *, reserve_cleanup_band: bool) -> int | None:
    return extend_eta_with_postprocess(
        eta_seconds,
        cleanup_eta_seconds,
        None,
        reserve_postprocess_band=reserve_cleanup_band,
    )


def map_postprocess_stage_progress(
    progress: float,
    *,
    stage: str,
    cleanup_requested: bool,
    caption_requested: bool,
) -> float:
    clamped = max(0.0, min(1.0, float(progress)))
    normalized = str(stage or "").strip().lower()
    if normalized == "cleanup":
        if caption_requested:
            return _remap(clamped, source_start=0.0, source_end=1.0, target_start=0.72, target_end=0.82)
        return _remap(clamped, source_start=0.0, source_end=1.0, target_start=0.72, target_end=0.96)
    if normalized == "captions":
        if cleanup_requested:
            return _remap(clamped, source_start=0.0, source_end=1.0, target_start=0.82, target_end=0.97)
        return _remap(clamped, source_start=0.0, source_end=1.0, target_start=0.72, target_end=0.97)
    return clamped


def extend_eta_with_postprocess(
    eta_seconds: int | None,
    cleanup_eta_seconds: int | None,
    caption_eta_seconds: int | None,
    *,
    reserve_postprocess_band: bool,
) -> int | None:
    if not reserve_postprocess_band:
        return eta_seconds
    extra_seconds = max(0, int(cleanup_eta_seconds or 0)) + max(0, int(caption_eta_seconds or 0))
    if eta_seconds is None:
        return None
    if extra_seconds <= 0:
        return eta_seconds
    return max(eta_seconds + extra_seconds, extra_seconds)


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
