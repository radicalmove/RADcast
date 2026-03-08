"""Static constants used by RADcast."""

from __future__ import annotations

ALLOWED_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}
DEFAULT_ENHANCEMENT_MODEL = "resemble"
DEFAULT_ENHANCE_COMMAND = "radcast-enhance"
DEFAULT_ENHANCE_DEVICE = "cpu"
DEFAULT_ENHANCE_NFE = 32
DEFAULT_ENHANCE_LAMBD = 0.7
DEFAULT_ENHANCE_TAU = 0.5
DEFAULT_DEEPFILTERNET_COMMAND = "deepFilter"
DEFAULT_DEEPFILTERNET_MODEL = "DeepFilterNet3"
DEFAULT_DEEPFILTERNET_POST_FILTER = False
DEFAULT_SGMSE_COMMAND_TEMPLATE = ""
DEFAULT_ENHANCE_POSTFILTER = (
    "highpass=f=60,"
    "equalizer=f=135:t=q:w=1.15:g=4.0,"
    "equalizer=f=245:t=q:w=1.0:g=2.4,"
    "equalizer=f=3000:t=q:w=1.0:g=0.9,"
    "acompressor=threshold=-20dB:ratio=1.3:attack=35:release=120:makeup=1.0,"
    "loudnorm=I=-18:TP=-1.5:LRA=7"
)
DEFAULT_WORKER_FALLBACK_TIMEOUT_SECONDS = 40
DEFAULT_WORKER_ONLINE_WINDOW_SECONDS = 45
