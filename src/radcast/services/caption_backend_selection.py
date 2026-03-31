"""Caption backend selection policy for platform-specific local execution."""

from __future__ import annotations

from collections.abc import Iterable


class CaptionBackendSelectionError(RuntimeError):
    pass


def resolve_caption_backend_id(
    requested_backend: str | None,
    *,
    platform_name: str,
    runtime_context: str,
    available_backends: Iterable[str],
) -> str:
    requested = str(requested_backend or "auto").strip().lower() or "auto"
    platform_normalized = str(platform_name or "").strip().lower()
    runtime_normalized = str(runtime_context or "").strip().lower() or "server"
    available = {str(item).strip().lower() for item in available_backends if str(item).strip()}

    if requested != "auto":
        if requested not in available:
            raise CaptionBackendSelectionError(f"Requested caption backend '{requested}' is unavailable")
        return requested

    if runtime_normalized == "local_helper" and platform_normalized == "darwin":
        if "whispercpp" in available:
            return "whispercpp"
        if "faster_whisper" in available:
            return "faster_whisper"
        raise CaptionBackendSelectionError("No caption backend is available for macOS local helper execution")

    if "faster_whisper" in available:
        return "faster_whisper"
    if "whispercpp" in available:
        return "whispercpp"
    raise CaptionBackendSelectionError("No caption backend is available")
