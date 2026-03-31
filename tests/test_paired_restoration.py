from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from radcast.experiments.paired_restoration import (
    PairedSource,
    build_paired_dataset,
    discover_pairs,
    load_pairs_from_dataset_manifest,
    normalize_pair_key,
    split_for_pair_id,
)


def _write_wave(path: Path, audio: np.ndarray, sample_rate: int = 16_000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, audio.astype(np.float32), sample_rate, subtype="PCM_16")


def test_build_paired_dataset_writes_train_layout(tmp_path: Path) -> None:
    sample_rate = 16_000
    t = np.linspace(0, 4.0, int(sample_rate * 4.0), endpoint=False)
    clean = 0.2 * np.sin(2.0 * np.pi * 220.0 * t)
    noisy = clean + (0.02 * np.sin(2.0 * np.pi * 30.0 * t))

    noisy_path = tmp_path / "noisy.wav"
    clean_path = tmp_path / "clean.wav"
    _write_wave(noisy_path, noisy, sample_rate)
    _write_wave(clean_path, clean, sample_rate)

    records = build_paired_dataset(
        pairs=[PairedSource(pair_id="lecture-01", noisy_path=noisy_path, clean_path=clean_path)],
        output_dir=tmp_path / "dataset",
        sample_rate=16_000,
        segment_seconds=2.0,
        hop_seconds=2.0,
        valid_fraction=0.0,
    )

    assert len(records) == 2
    assert all(record.split == "train" for record in records)
    assert (tmp_path / "dataset" / "train" / "noisy" / "lecture-01-seg0000.wav").exists()
    assert (tmp_path / "dataset" / "train" / "clean" / "lecture-01-seg0000.wav").exists()
    assert all(record.clean_active_ratio > 0.9 for record in records)
    assert all(record.envelope_correlation > 0.9 for record in records)

    manifest_lines = (tmp_path / "dataset" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    payload = json.loads(manifest_lines[0])
    assert payload["noisy_path"] == "train/noisy/lecture-01-seg0000.wav"
    assert payload["clean_path"] == "train/clean/lecture-01-seg0000.wav"
    assert payload["clean_active_ratio"] > 0.9
    assert payload["envelope_correlation"] > 0.9
    assert (tmp_path / "dataset" / "README.md").exists()


def test_build_paired_dataset_skips_inactive_segments(tmp_path: Path) -> None:
    sample_rate = 16_000
    silence = np.zeros(sample_rate * 2, dtype=np.float32)
    tone_t = np.linspace(0, 2.0, sample_rate * 2, endpoint=False)
    speech = 0.2 * np.sin(2.0 * np.pi * 220.0 * tone_t)

    noisy = np.concatenate([silence, speech])
    clean = np.concatenate([silence, speech])

    noisy_path = tmp_path / "noisy.wav"
    clean_path = tmp_path / "clean.wav"
    _write_wave(noisy_path, noisy, sample_rate)
    _write_wave(clean_path, clean, sample_rate)

    records = build_paired_dataset(
        pairs=[PairedSource(pair_id="lecture-02", noisy_path=noisy_path, clean_path=clean_path)],
        output_dir=tmp_path / "dataset",
        sample_rate=16_000,
        segment_seconds=2.0,
        hop_seconds=2.0,
        valid_fraction=0.0,
    )

    assert len(records) >= 1
    assert all(record.clean_active_ratio >= 0.4 for record in records)
    assert records[0].segment_id == "lecture-02-seg0000"


def test_build_paired_dataset_speech_centered_windows_reduce_trailing_silence(tmp_path: Path) -> None:
    sample_rate = 16_000
    lead = np.zeros(int(sample_rate * 2.0), dtype=np.float32)
    speech_t = np.linspace(0, 1.0, int(sample_rate * 1.0), endpoint=False)
    speech = 0.2 * np.sin(2.0 * np.pi * 220.0 * speech_t)
    tail = np.zeros(int(sample_rate * 2.0), dtype=np.float32)

    clean = np.concatenate([lead, speech, tail])
    noisy = clean + (0.005 * np.sin(2.0 * np.pi * 60.0 * np.linspace(0, 5.0, clean.size, endpoint=False))).astype(np.float32)

    noisy_path = tmp_path / "noisy.wav"
    clean_path = tmp_path / "clean.wav"
    _write_wave(noisy_path, noisy, sample_rate)
    _write_wave(clean_path, clean, sample_rate)

    centered = build_paired_dataset(
        pairs=[PairedSource(pair_id="lecture-03", noisy_path=noisy_path, clean_path=clean_path)],
        output_dir=tmp_path / "centered",
        sample_rate=16_000,
        segment_seconds=2.0,
        hop_seconds=1.0,
        valid_fraction=0.0,
    )
    sliding = build_paired_dataset(
        pairs=[PairedSource(pair_id="lecture-03", noisy_path=noisy_path, clean_path=clean_path)],
        output_dir=tmp_path / "sliding",
        sample_rate=16_000,
        segment_seconds=2.0,
        hop_seconds=1.0,
        valid_fraction=0.0,
        speech_centered=False,
    )

    assert len(centered) == 1
    assert len(sliding) >= 1
    assert centered[0].clean_active_ratio >= sliding[0].clean_active_ratio


def test_build_paired_dataset_preserves_explicit_split(tmp_path: Path) -> None:
    sample_rate = 16_000
    t = np.linspace(0, 2.0, int(sample_rate * 2.0), endpoint=False)
    clean = 0.2 * np.sin(2.0 * np.pi * 220.0 * t)
    noisy = clean
    noisy_path = tmp_path / "noisy.wav"
    clean_path = tmp_path / "clean.wav"
    _write_wave(noisy_path, noisy, sample_rate)
    _write_wave(clean_path, clean, sample_rate)

    records = build_paired_dataset(
        pairs=[PairedSource(pair_id="lecture-04", noisy_path=noisy_path, clean_path=clean_path, split="valid")],
        output_dir=tmp_path / "dataset",
        sample_rate=16_000,
        segment_seconds=2.0,
        hop_seconds=1.0,
        valid_fraction=0.0,
    )

    assert records
    assert all(record.split == "valid" for record in records)


def test_split_for_pair_id_is_stable() -> None:
    assert split_for_pair_id("lecture-01", valid_fraction=0.2) == split_for_pair_id("lecture-01", valid_fraction=0.2)


def test_normalize_pair_key_handles_cleaned_and_audio_suffixes() -> None:
    assert normalize_pair_key("CRJU150-24S1-Week-12-May30-LecA_audio") == "crju150 24s1 week 12 may30 leca"
    assert normalize_pair_key("Cleaned up 7.2 Whakapapa Tapu Noa Mana") == "7 2 whakapapa tapu noa mana"


def test_discover_pairs_matches_clean_and_noisy_files() -> None:
    discovered = discover_pairs(
        noisy_files=[
            Path("/tmp/Full lectures/CRJU150-24S1-Week-12-May30-LecA_audio.mp3"),
            Path("/tmp/Audio/7.2 Whakapapa, Tapu, Noa, Mana.mp3"),
        ],
        clean_files=[
            Path("/tmp/Cleaned up audio/Cleaned up full lectures/CRJU150-24S1-Week-12-May30-LecA.mp3"),
            Path("/tmp/Cleaned up audio/7.2 Whakapapa Tapu Noa Mana.mp3"),
        ],
    )
    assert [item.pair_id for item in discovered] == [
        "7.2-Whakapapa-Tapu-Noa-Mana",
        "CRJU150-24S1-Week-12-May30-LecA",
    ]


def test_load_pairs_from_dataset_manifest_resolves_relative_paths(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    (dataset / "train" / "noisy").mkdir(parents=True)
    (dataset / "train" / "clean").mkdir(parents=True)
    noisy = dataset / "train" / "noisy" / "seg0000.wav"
    clean = dataset / "train" / "clean" / "seg0000.wav"
    _write_wave(noisy, np.zeros(160, dtype=np.float32))
    _write_wave(clean, np.zeros(160, dtype=np.float32))
    manifest = dataset / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "segment_id": "lecture-01-seg0000",
                "pair_id": "lecture-01",
                "split": "valid",
                "noisy_path": "train/noisy/seg0000.wav",
                "clean_path": "train/clean/seg0000.wav",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    pairs = load_pairs_from_dataset_manifest(manifest)
    assert len(pairs) == 1
    assert pairs[0].pair_id == "lecture-01-seg0000"
    assert pairs[0].split == "valid"
    assert pairs[0].noisy_path == noisy.resolve()
    assert pairs[0].clean_path == clean.resolve()
