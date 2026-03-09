"""Build paired noisy/clean speech datasets for restoration experiments."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import soundfile as sf


@dataclass(frozen=True)
class PairedSource:
    pair_id: str
    noisy_path: Path
    clean_path: Path


@dataclass(frozen=True)
class SegmentRecord:
    segment_id: str
    pair_id: str
    split: str
    duration_seconds: float
    sample_rate: int
    noisy_path: Path
    clean_path: Path
    source_noisy_path: Path
    source_clean_path: Path


@dataclass(frozen=True)
class DiscoveredPair:
    pair_id: str
    noisy_path: Path
    clean_path: Path
    noisy_key: str
    clean_key: str


def sanitize_pair_id(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return normalized or "pair"


def normalize_pair_key(value: str) -> str:
    text = value.casefold()
    text = text.replace("_audio", " ")
    text = text.replace("cleaned up", " ")
    text = text.replace("adobepodcast", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [token for token in text.split() if token not in {"audio", "lecture", "lectures", "full"}]
    return " ".join(tokens).strip()


def split_for_pair_id(pair_id: str, *, valid_fraction: float = 0.2) -> str:
    if valid_fraction <= 0:
        return "train"
    digest = hashlib.sha1(pair_id.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") / float(1 << 64)
    return "valid" if bucket < valid_fraction else "train"


def parse_pair_argument(raw: str) -> PairedSource:
    if "::" not in raw:
        raise ValueError("pair arguments must use /path/to/noisy::/path/to/clean")
    noisy_raw, clean_raw = raw.split("::", 1)
    noisy_path = Path(noisy_raw).expanduser().resolve()
    clean_path = Path(clean_raw).expanduser().resolve()
    if not noisy_path.exists():
        raise FileNotFoundError(noisy_path)
    if not clean_path.exists():
        raise FileNotFoundError(clean_path)
    pair_id = sanitize_pair_id(clean_path.stem or noisy_path.stem)
    return PairedSource(pair_id=pair_id, noisy_path=noisy_path, clean_path=clean_path)


def discover_pairs(
    *,
    noisy_files: Iterable[Path],
    clean_files: Iterable[Path],
) -> list[DiscoveredPair]:
    clean_by_key: dict[str, Path] = {}
    clean_resolved: set[Path] = set()
    for clean_path in clean_files:
        resolved_clean = clean_path.resolve()
        clean_resolved.add(resolved_clean)
        key = normalize_pair_key(clean_path.stem)
        if key:
            clean_by_key[key] = resolved_clean

    discovered: list[DiscoveredPair] = []
    seen: set[tuple[str, Path, Path]] = set()
    for noisy_path in noisy_files:
        resolved_noisy = noisy_path.resolve()
        if resolved_noisy in clean_resolved:
            continue
        key = normalize_pair_key(noisy_path.stem)
        clean_path = clean_by_key.get(key)
        if not key or clean_path is None:
            continue
        pair_key = (sanitize_pair_id(clean_path.stem or noisy_path.stem), resolved_noisy, clean_path)
        if pair_key in seen:
            continue
        seen.add(pair_key)
        pair_id = sanitize_pair_id(clean_path.stem or noisy_path.stem)
        discovered.append(
            DiscoveredPair(
                pair_id=pair_id,
                noisy_path=resolved_noisy,
                clean_path=clean_path,
                noisy_key=key,
                clean_key=key,
            )
        )
    return sorted(discovered, key=lambda item: item.pair_id)


def write_pairs_jsonl(pairs: Iterable[DiscoveredPair | PairedSource], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for pair in pairs:
            handle.write(
                json.dumps(
                    {
                        "pair_id": pair.pair_id,
                        "noisy_path": str(pair.noisy_path),
                        "clean_path": str(pair.clean_path),
                    },
                    ensure_ascii=True,
                )
                + "\n"
            )


def load_pairs_jsonl(path: Path) -> list[PairedSource]:
    entries: list[PairedSource] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        noisy_path = Path(payload["noisy_path"]).expanduser().resolve()
        clean_path = Path(payload["clean_path"]).expanduser().resolve()
        pair_id = sanitize_pair_id(str(payload.get("pair_id") or clean_path.stem or noisy_path.stem))
        entries.append(PairedSource(pair_id=pair_id, noisy_path=noisy_path, clean_path=clean_path))
    return entries


def build_paired_dataset(
    *,
    pairs: Iterable[PairedSource],
    output_dir: Path,
    sample_rate: int = 48_000,
    segment_seconds: float = 8.0,
    hop_seconds: float = 4.0,
    activity_threshold_db: float = -38.0,
    min_active_ratio: float = 0.30,
    valid_fraction: float = 0.2,
    overwrite: bool = False,
) -> list[SegmentRecord]:
    destination = output_dir.resolve()
    if destination.exists() and any(destination.iterdir()) and not overwrite:
        raise FileExistsError(f"{destination} already exists and is not empty")
    destination.mkdir(parents=True, exist_ok=True)

    records: list[SegmentRecord] = []
    manifest_path = destination / "manifest.jsonl"

    if overwrite and manifest_path.exists():
        manifest_path.unlink()

    pairs_list = list(pairs)
    if not pairs_list:
        raise ValueError("At least one noisy/clean pair is required")

    with tempfile.TemporaryDirectory(prefix="radcast_paired_dataset_") as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        for pair in pairs_list:
            split = split_for_pair_id(pair.pair_id, valid_fraction=valid_fraction)
            noisy_wav = temp_dir / f"{pair.pair_id}.noisy.wav"
            clean_wav = temp_dir / f"{pair.pair_id}.clean.wav"
            _ffmpeg_to_mono_wav(pair.noisy_path, noisy_wav, sample_rate=sample_rate)
            _ffmpeg_to_mono_wav(pair.clean_path, clean_wav, sample_rate=sample_rate)

            noisy_audio, noisy_sr = sf.read(noisy_wav)
            clean_audio, clean_sr = sf.read(clean_wav)
            if noisy_sr != clean_sr:
                raise RuntimeError("normalized pair sample rates differ unexpectedly")
            noisy_mono = _to_mono(noisy_audio)
            clean_mono = _to_mono(clean_audio)
            total_samples = min(len(noisy_mono), len(clean_mono))
            if total_samples <= 0:
                continue

            noisy_mono = noisy_mono[:total_samples]
            clean_mono = clean_mono[:total_samples]
            segment_samples = max(1, int(round(segment_seconds * noisy_sr)))
            hop_samples = max(1, int(round(hop_seconds * noisy_sr)))

            split_noisy_dir = destination / split / "noisy"
            split_clean_dir = destination / split / "clean"
            split_noisy_dir.mkdir(parents=True, exist_ok=True)
            split_clean_dir.mkdir(parents=True, exist_ok=True)

            segment_index = 0
            for start_sample in range(0, max(total_samples - segment_samples + 1, 1), hop_samples):
                end_sample = min(total_samples, start_sample + segment_samples)
                if end_sample - start_sample < int(0.75 * segment_samples):
                    continue

                noisy_chunk = noisy_mono[start_sample:end_sample]
                clean_chunk = clean_mono[start_sample:end_sample]
                if not _segment_is_active(
                    clean_chunk,
                    sample_rate=noisy_sr,
                    threshold_db=activity_threshold_db,
                    min_active_ratio=min_active_ratio,
                ):
                    continue

                segment_id = f"{pair.pair_id}-seg{segment_index:04d}"
                noisy_output = split_noisy_dir / f"{segment_id}.wav"
                clean_output = split_clean_dir / f"{segment_id}.wav"
                sf.write(noisy_output, noisy_chunk, noisy_sr, subtype="PCM_16")
                sf.write(clean_output, clean_chunk, noisy_sr, subtype="PCM_16")

                record = SegmentRecord(
                    segment_id=segment_id,
                    pair_id=pair.pair_id,
                    split=split,
                    duration_seconds=len(noisy_chunk) / float(noisy_sr),
                    sample_rate=noisy_sr,
                    noisy_path=noisy_output.relative_to(destination),
                    clean_path=clean_output.relative_to(destination),
                    source_noisy_path=pair.noisy_path,
                    source_clean_path=pair.clean_path,
                )
                records.append(record)
                segment_index += 1

    with manifest_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(_segment_record_to_json(record), ensure_ascii=True) + "\n")

    _write_training_readme(
        destination=destination,
        sample_rate=sample_rate,
        segment_seconds=segment_seconds,
        hop_seconds=hop_seconds,
        valid_fraction=valid_fraction,
    )
    return records


def _ffmpeg_to_mono_wav(src: Path, dst: Path, *, sample_rate: int) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "ffmpeg failed").strip()
        raise RuntimeError(message)


def _to_mono(audio: np.ndarray) -> np.ndarray:
    if audio.ndim == 1:
        return audio.astype(np.float32, copy=False)
    return audio.mean(axis=1).astype(np.float32, copy=False)


def _segment_is_active(
    audio: np.ndarray,
    *,
    sample_rate: int,
    threshold_db: float,
    min_active_ratio: float,
) -> bool:
    frame_samples = max(1, int(round(sample_rate * 0.04)))
    hop_samples = max(1, int(round(sample_rate * 0.02)))
    frame_count = 0
    active_count = 0
    for start in range(0, max(len(audio) - frame_samples + 1, 1), hop_samples):
        end = min(len(audio), start + frame_samples)
        frame = audio[start:end]
        if frame.size == 0:
            continue
        rms = float(np.sqrt(np.mean(np.square(frame)) + 1e-12))
        db = 20.0 * np.log10(rms + 1e-12)
        frame_count += 1
        if db >= threshold_db:
            active_count += 1
    if frame_count == 0:
        return False
    return (active_count / float(frame_count)) >= min_active_ratio


def _segment_record_to_json(record: SegmentRecord) -> dict[str, object]:
    return {
        "segment_id": record.segment_id,
        "pair_id": record.pair_id,
        "split": record.split,
        "duration_seconds": round(record.duration_seconds, 6),
        "sample_rate": record.sample_rate,
        "noisy_path": record.noisy_path.as_posix(),
        "clean_path": record.clean_path.as_posix(),
        "source_noisy_path": str(record.source_noisy_path),
        "source_clean_path": str(record.source_clean_path),
    }


def _write_training_readme(
    *,
    destination: Path,
    sample_rate: int,
    segment_seconds: float,
    hop_seconds: float,
    valid_fraction: float,
) -> None:
    content = (
        "# Paired Restoration Dataset\n\n"
        "This dataset was built for RADcast speech-restoration experiments.\n\n"
        "Layout:\n"
        "- `train/clean/*.wav`\n"
        "- `train/noisy/*.wav`\n"
        "- `valid/clean/*.wav`\n"
        "- `valid/noisy/*.wav`\n"
        "- `manifest.jsonl`\n\n"
        "Build settings:\n"
        f"- sample rate: `{sample_rate}`\n"
        f"- segment length: `{segment_seconds}` seconds\n"
        f"- hop length: `{hop_seconds}` seconds\n"
        f"- valid fraction: `{valid_fraction}`\n\n"
        "This layout matches the base directory structure expected by the official SGMSE training code.\n"
    )
    (destination / "README.md").write_text(content, encoding="utf-8")
