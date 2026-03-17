# RADcast

RADcast is a local-first audio enhancement app for cleaning up lecture recordings.

## What it does
- Project picker flow (create/open)
- Project sharing (owner grants collaborator emails)
- Multiple enhancement backends with a default optimized lecture-cleanup path
- Default `RADcast Optimized` chain: chunked dereverb + Resemble Enhance + tuned mastering
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
RADcast has multiple enhancement backends. The default production path is `RADcast Optimized`.

Defaults:
- enhancement model: `studio_v18` (`RADcast Optimized`)
- command: `radcast-studio-enhance`
- device: `cpu`
- studio v18 tuning label: `RADcast Optimized`

Source-of-truth documentation for the default model lives here:
- [`docs/radcast_optimized.md`](/Users/rcd58/RADcast/docs/radcast_optimized.md)

`RADcast Optimized` defaults:
- dereverb method: `nara`
- no FFmpeg prefilter by default
- `nfe: 32`
- `lambd: 0.62`
- `tau: 0.45`
- `nara chunk seconds: 8.0`
- `nara overlap seconds: 1.0`
- `nara taps: 6`
- `nara delay: 2`
- `nara iterations: 1`
- `nara psd context: 1`
- tuning label: `RADcast Optimized`

Environment variables for the default model:
- `RADCAST_DEFAULT_ENHANCEMENT_MODEL`
- `RADCAST_STUDIO_COMMAND`
- `RADCAST_STUDIO_V18_TUNING_LABEL`
- `RADCAST_STUDIO_V18_DEREVERB_METHOD`
- `RADCAST_STUDIO_V18_ENHANCE_DEVICE`
- `RADCAST_STUDIO_V18_PREFILTER`
- `RADCAST_STUDIO_V18_NFE`
- `RADCAST_STUDIO_V18_LAMBD`
- `RADCAST_STUDIO_V18_TAU`
- `RADCAST_STUDIO_V18_NARA_CHUNK_SECONDS`
- `RADCAST_STUDIO_V18_NARA_OVERLAP_SECONDS`
- `RADCAST_STUDIO_V18_NARA_TAPS`
- `RADCAST_STUDIO_V18_NARA_DELAY`
- `RADCAST_STUDIO_V18_NARA_ITERATIONS`
- `RADCAST_STUDIO_V18_NARA_PSD_CONTEXT`
- `RADCAST_STUDIO_V18_POSTFILTER`

Legacy backend variables still exist for non-default models:
- `RADCAST_ENHANCE_COMMAND`
- `RADCAST_ENHANCE_DEVICE`
- `RADCAST_ENHANCE_NFE`
- `RADCAST_ENHANCE_LAMBD`
- `RADCAST_ENHANCE_TAU`
- `RADCAST_ENHANCE_PREFILTER`
- `RADCAST_ENHANCE_POSTFILTER`
- `RADCAST_AUDIO_TUNING_LABEL`
- `RADCAST_DEEPFILTERNET_COMMAND`
- `RADCAST_DEEPFILTERNET_MODEL`
- `RADCAST_DEEPFILTERNET_POST_FILTER`

For Ubuntu CPU deployments, use [`scripts/install-linux-cpu.sh`](/Users/rcd58/RADcast/scripts/install-linux-cpu.sh). It installs the CPU PyTorch wheels, `torchcodec`, `deepspeed` without custom ops, `resemble-enhance`, and `nara-wpe`.

If the default optimized model appears unavailable, check that the active environment can import both `resemble_enhance` and `nara_wpe`. On Apple Silicon helpers, the bootstrap path now keeps the helper on the known-good `resemble-enhance` Torch stack (`torch 2.1.1`, `torchaudio 2.1.1`, `torchvision 0.16.1`) and leaves the optimized enhancement stage on `cpu` by default. `RADcast Optimized` still runs in-process inside the long-lived helper/server process, so repeated jobs reuse the loaded `Resemble` model instead of paying a fresh CLI cold start every time.

## Experimental paired restoration

RADcast also has a local-only experimental track for building paired `noisy -> clean` datasets so we can train a true speech-restoration model instead of only stacking enhancement and mastering.

See:
- [`docs/paired_restoration.md`](/Users/rcd58/RADcast/docs/paired_restoration.md)
- [`scripts/build_paired_restoration_dataset.py`](/Users/rcd58/RADcast/scripts/build_paired_restoration_dataset.py)
- [`scripts/discover_restoration_pairs.py`](/Users/rcd58/RADcast/scripts/discover_restoration_pairs.py)
- [`scripts/run_sgmse_train.py`](/Users/rcd58/RADcast/scripts/run_sgmse_train.py)

Use `python scripts/run_sgmse_train.py ... --smoke` for the first real end-to-end training probe. The upstream SGMSE Python environment also needs `torchcodec` installed.
