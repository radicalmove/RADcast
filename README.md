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
- postfilter: `Adobe-like mastering chain (cleanup, body, de-ess, compression, loudness)`

Environment variables:
- `RADCAST_DEFAULT_ENHANCEMENT_MODEL`
- `RADCAST_ENHANCE_COMMAND`
- `RADCAST_ENHANCE_DEVICE`
- `RADCAST_ENHANCE_NFE`
- `RADCAST_ENHANCE_LAMBD`
- `RADCAST_ENHANCE_TAU`
- `RADCAST_ENHANCE_POSTFILTER`
  - default: `highpass=f=60,equalizer=f=135:t=q:w=1.15:g=4.0,equalizer=f=245:t=q:w=1.0:g=2.4,equalizer=f=3000:t=q:w=1.0:g=0.9,acompressor=threshold=-20dB:ratio=1.3:attack=35:release=120:makeup=1.0,loudnorm=I=-18:TP=-1.5:LRA=7`
- `RADCAST_DEEPFILTERNET_COMMAND`
- `RADCAST_DEEPFILTERNET_MODEL`
- `RADCAST_DEEPFILTERNET_POST_FILTER`
- `RADCAST_SGMSE_COMMAND_TEMPLATE`
  - supports placeholders: `{input_dir}` `{output_dir}` `{input_file}` `{input_name}`

If `resemble-enhance` is not on PATH, install it or set `RADCAST_ENHANCE_COMMAND`.

For Ubuntu CPU deployments, use [`scripts/install-linux-cpu.sh`](/Users/rcd58/RADcast/scripts/install-linux-cpu.sh). It installs the CPU PyTorch wheels, `torchcodec`, `deepspeed` without custom ops, and `resemble-enhance`.
