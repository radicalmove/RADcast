"""Static constants used by RADcast."""

from __future__ import annotations

ALLOWED_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}
DEFAULT_ENHANCE_COMMAND = "radcast-enhance"
DEFAULT_ENHANCE_DEVICE = "cpu"
DEFAULT_ENHANCE_NFE = 32
DEFAULT_ENHANCE_LAMBD = 0.7
DEFAULT_ENHANCE_TAU = 0.5
DEFAULT_ENHANCE_POSTFILTER = (
    "highpass=f=60,"
    "equalizer=f=140:t=q:w=1.15:g=3.5,"
    "equalizer=f=260:t=q:w=1.0:g=2.2,"
    "equalizer=f=3200:t=q:w=1.0:g=1.1,"
    "deesser=i=0.18:m=0.5:f=0.5:s=o,"
    "acompressor=threshold=-18dB:ratio=2.2:attack=20:release=180:makeup=2.5,"
    "loudnorm=I=-18:TP=-1.5:LRA=7"
)
DEFAULT_WORKER_FALLBACK_TIMEOUT_SECONDS = 40
DEFAULT_WORKER_ONLINE_WINDOW_SECONDS = 45
