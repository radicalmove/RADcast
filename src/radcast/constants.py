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
    "equalizer=f=135:t=q:w=1.15:g=4.2,"
    "equalizer=f=250:t=q:w=1.0:g=2.6,"
    "equalizer=f=3000:t=q:w=1.0:g=0.8,"
    "deesser=i=0.10:m=0.35:f=0.5:s=o,"
    "acompressor=threshold=-18dB:ratio=1.7:attack=25:release=140:makeup=1.6,"
    "loudnorm=I=-18:TP=-1.5:LRA=7"
)
DEFAULT_WORKER_FALLBACK_TIMEOUT_SECONDS = 40
DEFAULT_WORKER_ONLINE_WINDOW_SECONDS = 45
