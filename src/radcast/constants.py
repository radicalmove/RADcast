"""Static constants used by RADcast."""

from __future__ import annotations

ALLOWED_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}
DEFAULT_ENHANCEMENT_MODEL = "resemble"
DEFAULT_ENHANCE_COMMAND = "radcast-enhance"
DEFAULT_ENHANCE_DEVICE = "cpu"
DEFAULT_ENHANCE_NFE = 32
DEFAULT_ENHANCE_LAMBD = 0.7
DEFAULT_ENHANCE_TAU = 0.5
DEFAULT_STUDIO_COMMAND = "radcast-studio-enhance"
DEFAULT_STUDIO_V18_NFE = 32
DEFAULT_STUDIO_V18_LAMBD = 0.62
DEFAULT_STUDIO_V18_TAU = 0.45
DEFAULT_STUDIO_V18_WPE_TAPS = 12
DEFAULT_STUDIO_V18_WPE_DELAY = 4
DEFAULT_STUDIO_V18_WPE_ITERATIONS = 3
DEFAULT_STUDIO_V18_POSTFILTER = (
    "highpass=f=65,"
    "equalizer=f=142:t=q:w=1.05:g=4.15,"
    "equalizer=f=200:t=q:w=1.0:g=1.85,"
    "equalizer=f=315:t=q:w=1.0:g=-0.55,"
    "equalizer=f=455:t=q:w=1.0:g=-0.2,"
    "equalizer=f=2350:t=q:w=1.0:g=-1.45,"
    "equalizer=f=3000:t=q:w=1.0:g=-0.95,"
    "deesser=i=0.045:m=0.18:f=0.5:s=o,"
    "equalizer=f=5700:t=q:w=1.0:g=-1.15,"
    "equalizer=f=6400:t=q:w=1.0:g=-0.95,"
    "loudnorm=I=-20.5:TP=-1.5:LRA=8,"
    "lowpass=f=7750"
)
DEFAULT_DEEPFILTERNET_COMMAND = "deepFilter"
DEFAULT_DEEPFILTERNET_MODEL = "DeepFilterNet3"
DEFAULT_DEEPFILTERNET_POST_FILTER = False
DEFAULT_ENHANCE_PREFILTER = (
    "highpass=f=85,"
    "agate=threshold=0.027:ratio=1.26:attack=8:release=280:range=0.56:knee=4,"
    "afftdn=nr=4:nf=-48:tn=1,"
    "equalizer=f=380:t=q:w=1.0:g=-1.0,"
    "equalizer=f=6800:t=q:w=1.2:g=-1.3"
)
DEFAULT_ENHANCE_POSTFILTER = (
    "highpass=f=65,"
    "equalizer=f=150:t=q:w=1.05:g=2.8,"
    "equalizer=f=320:t=q:w=1.0:g=-1.2,"
    "equalizer=f=520:t=q:w=1.0:g=-0.9,"
    "equalizer=f=2800:t=q:w=1.0:g=0.4,"
    "deesser=i=0.06:m=0.25:f=0.5:s=o,"
    "loudnorm=I=-20.5:TP=-1.5:LRA=8,"
    "equalizer=f=6200:t=q:w=1.2:g=-2.5,"
    "lowpass=f=6800"
)
DEFAULT_STUDIO_POSTFILTER = (
    "highpass=f=65,"
    "equalizer=f=150:t=q:w=1.05:g=2.2,"
    "equalizer=f=320:t=q:w=1.0:g=-1.0,"
    "equalizer=f=520:t=q:w=1.0:g=-0.8,"
    "equalizer=f=2600:t=q:w=1.0:g=-2.0,"
    "equalizer=f=3400:t=q:w=1.0:g=-1.4,"
    "deesser=i=0.03:m=0.18:f=0.5:s=o,"
    "loudnorm=I=-20.5:TP=-1.5:LRA=8,"
    "equalizer=f=7000:t=q:w=1.0:g=0.8,"
    "lowpass=f=9500"
)
DEFAULT_AUDIO_TUNING_LABEL = "Version 7"
DEFAULT_STUDIO_V18_TUNING_LABEL = "Version 18"
DEFAULT_WORKER_FALLBACK_TIMEOUT_SECONDS = 40
DEFAULT_WORKER_ONLINE_WINDOW_SECONDS = 45
