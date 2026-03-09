# RADcast

RADcast is a local-first audio enhancement app for cleaning up lecture recordings.

## What it does
- Project picker flow (create/open)
- Project sharing (owner grants collaborator emails)
- One-pass audio enhancement using Resemble Enhance command-line tooling
- Progress bar + status updates
- WAV or MP3 output
- Download/play completed versions

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
bash scripts/install-linux-cpu.sh
pip install -e .[dev]
```

## Run

```bash
export RADCAST_HOST=127.0.0.1
export RADCAST_PORT=8012
radcast-api
```

## Enhancement engine
RADcast calls an external enhancement command.

Defaults:
- enhancement model: `resemble`
- command: `radcast-enhance`
- device: `cpu`
- nfe: `32`
- lambd: `0.7`
- tau: `0.5`
- prefilter: `highpass=f=85,agate=threshold=0.024:ratio=1.22:attack=10:release=240:range=0.5:knee=4,equalizer=f=380:t=q:w=1.0:g=-1.0,equalizer=f=6800:t=q:w=1.2:g=-1.4`
- postfilter: `highpass=f=65,equalizer=f=150:t=q:w=1.05:g=2.8,equalizer=f=320:t=q:w=1.0:g=-1.2,equalizer=f=520:t=q:w=1.0:g=-0.9,equalizer=f=2800:t=q:w=1.0:g=0.4,deesser=i=0.06:m=0.25:f=0.5:s=o,loudnorm=I=-20.5:TP=-1.5:LRA=8`
- audio tuning label: `Version 5`

Environment variables:
- `RADCAST_DEFAULT_ENHANCEMENT_MODEL`
- `RADCAST_ENHANCE_COMMAND`
- `RADCAST_ENHANCE_DEVICE`
- `RADCAST_ENHANCE_NFE`
- `RADCAST_ENHANCE_LAMBD`
- `RADCAST_ENHANCE_TAU`
- `RADCAST_ENHANCE_PREFILTER`
  - default: `highpass=f=85,agate=threshold=0.024:ratio=1.22:attack=10:release=240:range=0.5:knee=4,equalizer=f=380:t=q:w=1.0:g=-1.0,equalizer=f=6800:t=q:w=1.2:g=-1.4`
  - applies before enhancement to trim room tail and slightly tame sibilance before the model reconstructs speech
- `RADCAST_ENHANCE_POSTFILTER`
  - default: `highpass=f=65,equalizer=f=150:t=q:w=1.05:g=2.8,equalizer=f=320:t=q:w=1.0:g=-1.2,equalizer=f=520:t=q:w=1.0:g=-0.9,equalizer=f=2800:t=q:w=1.0:g=0.4,deesser=i=0.06:m=0.25:f=0.5:s=o,loudnorm=I=-20.5:TP=-1.5:LRA=8`
- `RADCAST_AUDIO_TUNING_LABEL`
  - default: `Version 5`
- `RADCAST_DEEPFILTERNET_COMMAND`
- `RADCAST_DEEPFILTERNET_MODEL`
- `RADCAST_DEEPFILTERNET_POST_FILTER`
- `RADCAST_SGMSE_COMMAND_TEMPLATE`
  - supports placeholders: `{input_dir}` `{output_dir}` `{input_file}` `{input_name}`

If `resemble-enhance` is not on PATH, install it or set `RADCAST_ENHANCE_COMMAND`.

For Ubuntu CPU deployments, use [`scripts/install-linux-cpu.sh`](/Users/rcd58/RADcast/scripts/install-linux-cpu.sh). It installs the CPU PyTorch wheels, `torchcodec`, `deepspeed` without custom ops, and `resemble-enhance`.
