#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt

# Clean out any accidental GPU torch packages before installing the CPU wheels.
python -m pip uninstall -y torch torchaudio torchvision ptflops || true

python -m pip install --no-deps --force-reinstall \
  "https://download.pytorch.org/whl/cpu/torch-2.10.0%2Bcpu-cp312-cp312-manylinux_2_28_x86_64.whl" \
  "https://download.pytorch.org/whl/cpu/torchaudio-2.10.0%2Bcpu-cp312-cp312-manylinux_2_28_x86_64.whl"

python -m pip install \
  "numpy==1.26.4" \
  "nara-wpe==0.0.11" \
  "scipy==1.17.1" \
  "soundfile==0.13.1" \
  "librosa==0.11.0" \
  "matplotlib==3.10.8" \
  "omegaconf==2.3.0" \
  "pandas==2.3.3" \
  "rich==14.3.3" \
  "tqdm==4.67.3" \
  "resampy==0.4.3" \
  "torchcodec==0.10.0"

DS_BUILD_OPS=0 python -m pip install "deepspeed==0.18.7"
python -m pip install --no-deps "git+https://github.com/resemble-ai/resemble-enhance.git"
