# Paired Restoration Track

This is the experimental RADcast path for learning a cleaner, drier, more close-mic sound from paired examples.

Current approach:
- keep the shipped enhancement backends unchanged
- prepare a paired `noisy -> clean` dataset from real lecture audio and a higher-quality target
- use that dataset for a trainable speech-restoration model rather than another FFmpeg-only chain

Why this layout:
- the official SGMSE training code expects a base directory with:
  - `train/clean/*.wav`
  - `train/noisy/*.wav`
  - `valid/clean/*.wav`
  - `valid/noisy/*.wav`
- filenames must match between `clean` and `noisy`
- `.wav` only

Reference:
- SGMSE README: `python train.py --base_dir <your_base_dir>`
- for 48 kHz models, the official README suggests:
  - `--backbone ncsnpp_48k --n_fft 1534 --hop_length 384 --spec_factor 0.065 --spec_abs_exponent 0.667 --sigma-min 0.1 --sigma-max 1.0 --theta 2.0`

Dataset builder:

```bash
python scripts/build_paired_restoration_dataset.py \
  --pair "/path/to/lecture-original.wav::/path/to/adobe-target.wav" \
  --output-dir experiments/paired-restoration/run01 \
  --segment-seconds 8 \
  --hop-seconds 4 \
  --valid-fraction 0.2
```

Automatic pair discovery:

```bash
python scripts/discover_restoration_pairs.py \
  --noisy-dir "/path/to/original-audio" \
  --clean-dir "/path/to/cleaned-audio" \
  --output-jsonl experiments/paired-restoration/pairs.jsonl
```

Or with a JSONL manifest:

```json
{"pair_id": "tikanga-01", "noisy_path": "/path/to/original.wav", "clean_path": "/path/to/adobe.wav"}
```

```bash
python scripts/build_paired_restoration_dataset.py \
  --pairs-jsonl experiments/paired-restoration/pairs.jsonl \
  --output-dir experiments/paired-restoration/run01
```

Recommended targets:
- best: real close-mic recordings of the same speaker/content
- acceptable for bootstrapping: Adobe Podcast outputs as provisional `clean` targets

Official SGMSE training launch:

```bash
python scripts/run_sgmse_train.py \
  --sgmse-dir /path/to/sgmse \
  --dataset-dir experiments/paired-restoration/run01 \
  --log-dir experiments/paired-restoration/sgmse-logs \
  --wandb-name radcast-restoration-v1 \
  --dry-run
```

This runner is intentionally thin. It launches the official SGMSE `train.py` with the 48 kHz backbone defaults suggested in the upstream README.

Before the first real launch, install the upstream requirements into an isolated Python 3.11 environment and add `torchcodec`:

```bash
python3.11 -m venv ~/.venvs/sgmse311
source ~/.venvs/sgmse311/bin/activate
python -m pip install -r /path/to/sgmse/requirements.txt
python -m pip install torchcodec
```

Cheap smoke run:

```bash
python scripts/run_sgmse_train.py \
  --sgmse-dir /path/to/sgmse \
  --dataset-dir experiments/paired-restoration/run01 \
  --log-dir experiments/paired-restoration/sgmse-logs-smoke \
  --python ~/.venvs/sgmse311/bin/python \
  --wandb-name radcast-restoration-smoke \
  --smoke
```

Practical caution:
- Adobe outputs are useful as a pseudo-target for experiments, but they encode Adobe's own model biases
- long term, real far-field vs close-mic pairs are the better training target if we want a distinctive RADcast model
