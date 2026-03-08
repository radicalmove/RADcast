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
- command: `radcast-enhance`
- device: `cpu`
- nfe: `32`
- lambd: `0.7`
- tau: `0.5`
- postfilter: `170Hz/320Hz body lift + 4.5kHz treble trim`

Environment variables:
- `RADCAST_ENHANCE_COMMAND`
- `RADCAST_ENHANCE_DEVICE`
- `RADCAST_ENHANCE_NFE`
- `RADCAST_ENHANCE_LAMBD`
- `RADCAST_ENHANCE_TAU`
- `RADCAST_ENHANCE_POSTFILTER`
  - default: `equalizer=f=145:t=q:w=1.2:g=4,equalizer=f=285:t=q:w=1.0:g=2,equalizer=f=4500:t=q:w=0.9:g=-1.6`

If `resemble-enhance` is not on PATH, install it or set `RADCAST_ENHANCE_COMMAND`.

For Ubuntu CPU deployments, use [`scripts/install-linux-cpu.sh`](/Users/rcd58/RADcast/scripts/install-linux-cpu.sh). It installs the CPU PyTorch wheels, `torchcodec`, `deepspeed` without custom ops, and `resemble-enhance`.
