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
DEFAULT_ENHANCE_PREFILTER = (
    "highpass=f=85,"
    "agate=threshold=0.024:ratio=1.22:attack=10:release=240:range=0.5:knee=4,"
    "equalizer=f=380:t=q:w=1.0:g=-1.0,"
    "equalizer=f=6800:t=q:w=1.2:g=-1.4"
)
DEFAULT_ENHANCE_POSTFILTER = (
    "highpass=f=65,"
    "equalizer=f=150:t=q:w=1.05:g=2.8,"
    "equalizer=f=320:t=q:w=1.0:g=-1.2,"
    "equalizer=f=520:t=q:w=1.0:g=-0.9,"
    "equalizer=f=2800:t=q:w=1.0:g=0.4,"
    "deesser=i=0.06:m=0.25:f=0.5:s=o,"
    "loudnorm=I=-20.5:TP=-1.5:LRA=8"
)
DEFAULT_AUDIO_TUNING_LABEL = "Version 5"
DEFAULT_WORKER_FALLBACK_TIMEOUT_SECONDS = 40
DEFAULT_WORKER_ONLINE_WINDOW_SECONDS = 45
