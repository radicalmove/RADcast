"""Static constants used by RADcast."""

from __future__ import annotations

ALLOWED_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}
DEFAULT_ENHANCE_COMMAND = "radcast-enhance"
DEFAULT_ENHANCE_DEVICE = "cpu"
DEFAULT_ENHANCE_NFE = 32
DEFAULT_ENHANCE_LAMBD = 0.7
DEFAULT_ENHANCE_TAU = 0.5
DEFAULT_ENHANCE_POSTFILTER = (
    "equalizer=f=145:t=q:w=1.2:g=4,"
    "equalizer=f=285:t=q:w=1.0:g=2,"
    "equalizer=f=4500:t=q:w=0.9:g=-1.6"
)
DEFAULT_WORKER_FALLBACK_TIMEOUT_SECONDS = 40
DEFAULT_WORKER_ONLINE_WINDOW_SECONDS = 45
