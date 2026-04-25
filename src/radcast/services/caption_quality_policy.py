"""Quality policy for speech caption generation."""

from __future__ import annotations

from dataclasses import dataclass

from radcast.models import CaptionQualityMode


@dataclass(frozen=True)
class CaptionQualityPolicy:
    policy_id: str
    first_pass_backend_id: str
    first_pass_model_size: str
    first_pass_beam_size: int
    review_backend_id: str
    review_model_size: str
    review_beam_size: int
    review_strategy_id: str
    cue_shaping_strategy_id: str
    progress_label: str


def _normalize_text(value: str | None, *, fallback: str) -> str:
    resolved = str(value or "").strip()
    return resolved or fallback


def _normalize_mode(quality_mode: CaptionQualityMode | str) -> CaptionQualityMode:
    if isinstance(quality_mode, CaptionQualityMode):
        return quality_mode
    resolved = str(quality_mode or "").strip().lower()
    try:
        return CaptionQualityMode(resolved)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Unsupported caption quality mode: {quality_mode!r}") from exc


def _supports_mlx_model_size(model_size: str) -> bool:
    resolved = str(model_size or "").strip().lower()
    if not resolved:
        return False
    if "/" in resolved:
        return True
    return resolved in {"tiny", "base", "small", "medium", "large"}


def resolve_caption_quality_policy(
    *,
    quality_mode: CaptionQualityMode | str,
    runtime_context: str,
    platform_name: str,
    backend_id: str,
    first_pass_model_size: str,
    first_pass_beam_size: int,
    review_model_size: str,
    review_beam_size: int,
) -> CaptionQualityPolicy:
    normalized_mode = _normalize_mode(quality_mode)
    normalized_runtime = str(runtime_context or "").strip().lower() or "server"
    normalized_platform = str(platform_name or "").strip().lower()
    normalized_backend = str(backend_id or "").strip().lower() or "faster_whisper"
    normalized_first_pass_model_size = _normalize_text(first_pass_model_size, fallback="medium")
    normalized_review_model_size = _normalize_text(review_model_size, fallback=normalized_first_pass_model_size)
    normalized_first_pass_beam_size = max(1, int(first_pass_beam_size))
    normalized_review_beam_size = max(1, int(review_beam_size))

    is_macos_local_helper = normalized_runtime == "local_helper" and normalized_platform == "darwin"
    is_quality_local_lecture = (
        normalized_mode == CaptionQualityMode.REVIEWED
        and is_macos_local_helper
        and normalized_backend in {"whispercpp", "mlx_whisper"}
    )

    if normalized_mode == CaptionQualityMode.FAST:
        return CaptionQualityPolicy(
            policy_id="standard_fast",
            first_pass_backend_id=normalized_backend,
            first_pass_model_size=normalized_first_pass_model_size,
            first_pass_beam_size=normalized_first_pass_beam_size,
            review_backend_id=normalized_backend,
            review_model_size=normalized_first_pass_model_size,
            review_beam_size=normalized_first_pass_beam_size,
            review_strategy_id="none",
            cue_shaping_strategy_id="standard_caption",
            progress_label="fast captions",
        )

    if normalized_mode == CaptionQualityMode.ACCURATE:
        return CaptionQualityPolicy(
            policy_id="standard_accurate",
            first_pass_backend_id=normalized_backend,
            first_pass_model_size=normalized_first_pass_model_size,
            first_pass_beam_size=normalized_first_pass_beam_size,
            review_backend_id=normalized_backend,
            review_model_size=normalized_review_model_size,
            review_beam_size=normalized_review_beam_size,
            review_strategy_id="none",
            cue_shaping_strategy_id="standard_caption",
            progress_label="accurate captions",
        )

    if is_quality_local_lecture:
        resolved_review_model_size = normalized_review_model_size
        if normalized_backend == "mlx_whisper" and not _supports_mlx_model_size(resolved_review_model_size):
            if _supports_mlx_model_size("medium"):
                resolved_review_model_size = "medium"
            elif _supports_mlx_model_size(normalized_first_pass_model_size):
                resolved_review_model_size = normalized_first_pass_model_size
            else:
                resolved_review_model_size = "medium"
        return CaptionQualityPolicy(
            policy_id="quality_local_lecture",
            first_pass_backend_id=normalized_backend,
            first_pass_model_size=normalized_first_pass_model_size,
            first_pass_beam_size=normalized_first_pass_beam_size,
            review_backend_id=normalized_backend,
            review_model_size=resolved_review_model_size,
            review_beam_size=normalized_review_beam_size,
            review_strategy_id="targeted_review",
            cue_shaping_strategy_id="lecture_friendly",
            progress_label="lecture-quality captions",
        )

    return CaptionQualityPolicy(
        policy_id="standard_reviewed",
        first_pass_backend_id=normalized_backend,
        first_pass_model_size=normalized_first_pass_model_size,
        first_pass_beam_size=normalized_first_pass_beam_size,
        review_backend_id="faster_whisper",
        review_model_size=normalized_review_model_size,
        review_beam_size=normalized_review_beam_size,
        review_strategy_id="standard_review",
        cue_shaping_strategy_id="standard_caption",
        progress_label="reviewed captions",
    )
