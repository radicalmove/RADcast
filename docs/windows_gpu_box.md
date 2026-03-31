# Dedicated GPU Box Plan

This is the recommended setup for moving the `RADcast` restoration experiments off the main Mac and onto a dedicated Windows machine with:

- `GTX 1660 6GB`
- `16` CPU threads
- no competing day-to-day workload

## Why this machine

This box is a better experiment target than the Mac because:

- the restoration stack is much more CUDA-friendly than `MPS`-friendly
- long-running training and inference will not interfere with `RADTTS`/`RADcast` product work on the Mac
- the `16` CPU threads help with dataset loading, ffmpeg preprocessing, scoring, and concurrent evaluation jobs

The main constraint is VRAM. `6 GB` is enough for controlled restoration probes, but not for large or careless training runs.

## Recommended platform

Use `WSL2` with `Ubuntu`, not native Windows Python.

Why:

- the current experiment scripts assume a Linux shell workflow
- the local `SGMSE` checkout and patches are already Linux-first
- CUDA under WSL is officially supported for Pascal-and-later NVIDIA GPUs

Official references:

- Microsoft says the standard install path is `wsl --install` and then restart Windows. [Microsoft WSL install](https://learn.microsoft.com/en-us/windows/wsl/install)
- NVIDIA says CUDA becomes available inside `WSL 2` once the Windows NVIDIA driver is installed, and you should not install a Linux NVIDIA display driver inside WSL. [NVIDIA CUDA on WSL](https://docs.nvidia.com/cuda/pdf/CUDA_on_WSL_User_Guide.pdf)
- PyTorch recommends installing the current CUDA-enabled Linux wheel that matches your system from the official selector. [PyTorch Start Locally](https://docs.pytorch.org/get-started/locally/)

## Target configuration

Use these settings as the default experiment baseline on that machine:

- sample rate: `16 kHz`
- device: `cuda`
- batch size:
  - training: `1` or `2`
  - inference: `1`
- dataloader workers: `4-8`
- reverse steps for checkpoint comparison: `N=10`

Do not start with larger batch sizes on the `GTX 1660 6GB`.

## WSL setup

From an elevated PowerShell window:

```powershell
wsl --install
wsl --update
```

Then reboot, open Ubuntu, and install the Linux-side dependencies:

```bash
sudo apt update
sudo apt install -y \
  build-essential \
  ffmpeg \
  git \
  git-lfs \
  libsndfile1 \
  python3.11 \
  python3.11-venv \
  python3-pip \
  tmux \
  unzip
```

Do **not** install a Linux NVIDIA driver inside WSL.

Inside WSL, create the experiment environment:

```bash
python3.11 -m venv ~/.venvs/sgmse311
source ~/.venvs/sgmse311/bin/activate
python -m pip install --upgrade pip wheel setuptools
```

Then install the current CUDA-enabled PyTorch build using the command from the official PyTorch selector for:

- OS: `Linux`
- Package: `Pip`
- Language: `Python`
- Compute platform: `CUDA`

After that:

```bash
python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
```

Expected result:

- `torch.cuda.is_available()` is `True`
- device name resolves to the `GTX 1660`

## Transfer set

Minimum useful transfer from the Mac:

- `RADcast` repo
- patched `SGMSE` checkout
- paired dataset
- best current restoration checkpoint

Current local sizes on the Mac:

- `RADcast`: about `55 MB`
- `SGMSE`: about `74 MB`
- paired dataset `radcast-paired-restoration-crju150-16k`: about `3.3 GB`
- `best_v9_step50/step=50.ckpt`: about `1.0 GB`

Optional older baseline:

- `best_v7_step600/step=600.ckpt`: about `1.0 GB`

Generate a machine-readable manifest on the Mac:

```bash
cd /Users/rcd58/RADcast
python3 scripts/prepare_gpu_box_transfer.py \
  --radcast-root /Users/rcd58/RADcast \
  --sgmse-root /Users/rcd58/sgmse \
  --dataset-dir /Users/rcd58/Desktop/radcast-paired-restoration-crju150-16k \
  --checkpoint best_v9_step50=/Users/rcd58/Desktop/radcast-sgmse-runs/best_v9_step50/step=50.ckpt \
  --checkpoint best_v7_step600=/Users/rcd58/Desktop/radcast-sgmse-runs/best_v7_step600/step=600.ckpt \
  --output-json /Users/rcd58/Desktop/radcast-gpu-box-transfer.json
```

## Suggested directory layout on the GPU box

Inside WSL:

```text
~/radcast-gpu/
  RADcast/
  sgmse/
  datasets/
    radcast-paired-restoration-crju150-16k/
  checkpoints/
    best_v9_step50.ckpt
    best_v7_step600.ckpt
  runs/
```

Set:

```bash
export SGMSE_ROOT=$HOME/radcast-gpu/sgmse
```

## Best immediate use of the box

Do not start by moving the whole `RADcast` app runtime there.

Use the Windows box only for:

1. checkpoint inference
2. held-out comparison
3. small fine-tune probes
4. overnight restoration runs

Keep app/product work on the Mac.

## Held-out comparison command

Once files are copied into WSL, run:

```bash
source ~/.venvs/sgmse311/bin/activate
cd ~/radcast-gpu/RADcast

python scripts/run_restoration_checkpoint_compare.py \
  --sgmse-root "$HOME/radcast-gpu/sgmse" \
  --input-wav /path/to/heldout-noisy.wav \
  --target-wav /path/to/heldout-clean.wav \
  --checkpoint baseline600=$HOME/radcast-gpu/checkpoints/best_v7_step600.ckpt \
  --checkpoint best50=$HOME/radcast-gpu/checkpoints/best_v9_step50.ckpt \
  --output-dir $HOME/radcast-gpu/runs/heldout-compare \
  --device cuda \
  --N 10
```

This will produce:

- `baseline600.wav`
- `baseline600_report.txt`
- `baseline600_score.json`
- `best50.wav`
- `best50_report.txt`
- `best50_score.json`

## Training guidance for GTX 1660 6GB

Start conservative:

- `batch_size=1`
- `num_workers=4`
- `16 kHz`
- short probes first

If stable:

- move to `batch_size=2`
- raise workers to `6-8`

Do not run multiple GPU-heavy trainings at once. Use the spare CPU threads for:

- dataset generation
- ffmpeg conversion
- score/report generation
- one extra CPU-only comparison job

## Recommendation

Treat the dedicated GPU box as the restoration lab:

- Mac: application work, listening, deployment
- GPU box: restoration experiments only

That is the cleanest split and the best use of the hardware you have.
