#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torch.nn.functional as F
import torchaudio
from scipy.signal import resample_poly
from torch.serialization import add_safe_globals


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from radcast.experiments.restoration_eval import score_blocks


def _maybe_add_sgmse_root(path: str | None) -> None:
    if not path:
        return
    resolved = str(Path(path).expanduser().resolve())
    if resolved not in sys.path:
        sys.path.insert(0, resolved)


def _import_sgmse():
    try:
        from sgmse.data_module import SpecsDataModule
        from sgmse.model import ScoreModel
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "SGMSE is not importable. Provide --sgmse-root or set SGMSE_ROOT to the patched checkout."
        ) from exc
    add_safe_globals([SpecsDataModule])
    return ScoreModel


def load_mono_16k(path: Path) -> tuple[np.ndarray, int]:
    audio, sample_rate = sf.read(path)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sample_rate != 16000:
        audio = resample_poly(audio, 16000, sample_rate)
        sample_rate = 16000
    return audio.astype(np.float64), sample_rate


def rms_db(audio: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(audio**2)) + 1e-12))


def centroid(audio: np.ndarray, sample_rate: int) -> float:
    spectrum = np.abs(np.fft.rfft(audio * np.hanning(len(audio))))
    freqs = np.fft.rfftfreq(len(audio), 1 / sample_rate)
    return float((freqs * spectrum).sum() / (spectrum.sum() + 1e-12))


def band_rms_db(audio: np.ndarray, sample_rate: int, lo: int, hi: int) -> float:
    spectrum = np.fft.rfft(audio * np.hanning(len(audio)))
    freqs = np.fft.rfftfreq(len(audio), 1 / sample_rate)
    mask = (freqs >= lo) & (freqs < hi)
    if not np.any(mask):
        return float("-inf")
    power = np.mean(np.abs(spectrum[mask]) ** 2)
    return float(10 * np.log10(power + 1e-12))


def summarize(path: Path) -> dict[str, float]:
    audio, sample_rate = load_mono_16k(path)
    return {
        "duration_s": round(len(audio) / sample_rate, 3),
        "rms_db": round(rms_db(audio), 2),
        "centroid_hz": round(centroid(audio, sample_rate), 1),
        "band_0_250_db": round(band_rms_db(audio, sample_rate, 0, 250), 2),
        "band_250_700_db": round(band_rms_db(audio, sample_rate, 250, 700), 2),
        "band_700_2000_db": round(band_rms_db(audio, sample_rate, 700, 2000), 2),
        "band_2000_4500_db": round(band_rms_db(audio, sample_rate, 2000, 4500), 2),
        "band_4500_8000_db": round(band_rms_db(audio, sample_rate, 4500, 8000), 2),
    }


def parse_checkpoint_arg(raw: str) -> tuple[str, Path]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError("checkpoint must be NAME=PATH")
    name, path = raw.split("=", 1)
    cleaned_name = name.strip()
    if not cleaned_name:
        raise argparse.ArgumentTypeError("checkpoint name may not be empty")
    return cleaned_name, Path(path).expanduser().resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one or more restoration checkpoints against a local noisy/clean pair.")
    parser.add_argument("--sgmse-root", help="Path to the patched SGMSE checkout.")
    parser.add_argument("--input-wav", type=Path, required=True, help="Noisy input WAV/MP3 file.")
    parser.add_argument("--target-wav", type=Path, required=True, help="Clean target WAV/MP3 file used for scoring.")
    parser.add_argument(
        "--checkpoint",
        type=parse_checkpoint_arg,
        action="append",
        required=True,
        help="Checkpoint in the form NAME=/abs/path/to/file.ckpt. Can be repeated.",
    )
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for outputs, reports, and scores.")
    parser.add_argument("--device", default="cpu", help="torch device for enhancement, e.g. cuda or cpu.")
    parser.add_argument("--N", type=int, default=10, help="Number of reverse steps for model.enhance().")
    parser.add_argument("--keep-native-rate", action="store_true")
    parser.add_argument(
        "--segment-seconds",
        type=float,
        default=0.0,
        help="Process long files in overlapping segments of this length. Use 0 to disable chunking.",
    )
    parser.add_argument(
        "--segment-overlap-seconds",
        type=float,
        default=1.0,
        help="Crossfade overlap between chunked segments.",
    )
    return parser


def format_report(
    checkpoint_path: Path,
    output_path: Path,
    steps: int,
    original_stats: dict[str, float],
    restored_stats: dict[str, float],
    target_stats: dict[str, float],
) -> str:
    lines: list[str] = [
        f"checkpoint: {checkpoint_path}",
        f"output: {output_path}",
        f"N: {steps}",
        "",
        "original",
    ]
    for key, value in original_stats.items():
        lines.append(f"  {key}: {value}")
    lines.extend(["", "restored"])
    for key, value in restored_stats.items():
        lines.append(f"  {key}: {value}")
    lines.extend(["", "adobe"])
    for key, value in target_stats.items():
        lines.append(f"  {key}: {value}")
    return "\n".join(lines).rstrip() + "\n"


def _to_tensor_waveform(value: torch.Tensor | np.ndarray) -> torch.Tensor:
    if isinstance(value, np.ndarray):
        tensor = torch.from_numpy(value)
    else:
        tensor = value.detach().cpu()
    if tensor.ndim == 1:
        tensor = tensor.unsqueeze(0)
    return tensor.to(dtype=torch.float32)


def _chunk_weights(length: int, fade: int, fade_in: bool, fade_out: bool) -> torch.Tensor:
    weights = torch.ones(length, dtype=torch.float32)
    fade = min(fade, max(length - 1, 0))
    if fade <= 0:
        return weights
    if fade_in:
        weights[:fade] = torch.linspace(0.0, 1.0, fade, dtype=torch.float32)
    if fade_out:
        weights[-fade:] = torch.minimum(
            weights[-fade:],
            torch.linspace(1.0, 0.0, fade, dtype=torch.float32),
        )
    return weights


def enhance_waveform(
    *,
    model,
    waveform: torch.Tensor,
    output_sample_rate: int,
    steps: int,
    segment_seconds: float,
    overlap_seconds: float,
) -> torch.Tensor:
    if segment_seconds <= 0:
        with torch.no_grad():
            return _to_tensor_waveform(model.enhance(waveform, N=steps))

    total_samples = waveform.shape[-1]
    segment_samples = max(int(segment_seconds * output_sample_rate), 1)
    overlap_samples = max(int(overlap_seconds * output_sample_rate), 0)
    step_samples = max(segment_samples - overlap_samples, 1)
    if total_samples <= segment_samples:
        with torch.no_grad():
            return _to_tensor_waveform(model.enhance(waveform, N=steps))

    merged = torch.zeros((waveform.shape[0], total_samples), dtype=torch.float32)
    weights = torch.zeros((1, total_samples), dtype=torch.float32)
    starts = list(range(0, total_samples, step_samples))
    chunk_count = len(starts)

    for chunk_index, start in enumerate(starts, start=1):
        end = min(start + segment_samples, total_samples)
        expected_length = end - start
        chunk = waveform[:, start:end]
        with torch.no_grad():
            enhanced_chunk = _to_tensor_waveform(model.enhance(chunk, N=steps))
        if enhanced_chunk.shape[-1] < expected_length:
            enhanced_chunk = F.pad(enhanced_chunk, (0, expected_length - enhanced_chunk.shape[-1]))
        elif enhanced_chunk.shape[-1] > expected_length:
            enhanced_chunk = enhanced_chunk[..., :expected_length]

        chunk_weights = _chunk_weights(
            expected_length,
            overlap_samples,
            fade_in=start > 0,
            fade_out=end < total_samples,
        )
        merged[:, start:end] += enhanced_chunk * chunk_weights
        weights[:, start:end] += chunk_weights

        print(
            f"chunk {chunk_index}/{chunk_count}: {start / output_sample_rate:.1f}s"
            f"-{end / output_sample_rate:.1f}s"
        )
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    return merged / weights.clamp_min(1e-6)


def main() -> int:
    args = build_parser().parse_args()
    _maybe_add_sgmse_root(args.sgmse_root or os.environ.get("SGMSE_ROOT"))
    ScoreModel = _import_sgmse()

    input_path = args.input_wav.expanduser().resolve()
    target_path = args.target_wav.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    original_stats = summarize(input_path)
    target_stats = summarize(target_path)

    for name, checkpoint_path in args.checkpoint:
        model = ScoreModel.load_from_checkpoint(str(checkpoint_path), map_location=args.device)
        model.eval()
        waveform, sample_rate = torchaudio.load(str(input_path))
        if not args.keep_native_rate and sample_rate != model.sr:
            waveform = torchaudio.functional.resample(waveform, sample_rate, model.sr)
            output_sample_rate = model.sr
        else:
            output_sample_rate = sample_rate

        enhanced = enhance_waveform(
            model=model,
            waveform=waveform,
            output_sample_rate=output_sample_rate,
            steps=args.N,
            segment_seconds=args.segment_seconds,
            overlap_seconds=args.segment_overlap_seconds,
        )

        output_wav = output_dir / f"{name}.wav"
        enhanced_np = enhanced.squeeze(0).cpu().numpy()
        sf.write(str(output_wav), enhanced_np, output_sample_rate)

        restored_stats = summarize(output_wav)
        report_text = format_report(
            checkpoint_path=checkpoint_path,
            output_path=output_wav,
            steps=args.N,
            original_stats=original_stats,
            restored_stats=restored_stats,
            target_stats=target_stats,
        )

        report_path = output_dir / f"{name}_report.txt"
        report_path.write_text(report_text, encoding="utf-8")

        score_value, diffs = score_blocks(
            {
                "original": original_stats,
                "restored": restored_stats,
                "adobe": target_stats,
            }
        )
        score_payload = {"score": score_value, "diffs": diffs}
        score_path = output_dir / f"{name}_score.json"
        score_path.write_text(json.dumps(score_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        print(f"=== {name} ===")
        print(report_text)
        print(json.dumps(score_payload, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
