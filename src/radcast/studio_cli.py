"""Studio Cleanup backend: custom dereverb followed by Resemble Enhance."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import numpy as np
import resemble_enhance
import torch
import torchaudio
from resemble_enhance.enhancer.inference import enhance

from radcast.services.studio import suppress_late_reverb, wpe_dereverb


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Enhance audio with custom dereverb plus Resemble Enhance")
    parser.add_argument("in_dir", type=Path, help="Path to input audio folder")
    parser.add_argument("out_dir", type=Path, help="Output folder")
    parser.add_argument("--run_dir", type=Path, default=None, help="Optional model checkpoint folder")
    parser.add_argument("--suffix", type=str, default=".wav", help="Audio file suffix")
    parser.add_argument("--device", type=str, default="cpu", help="Execution device")
    parser.add_argument("--lambd", type=float, default=0.7, help="Denoise strength")
    parser.add_argument("--tau", type=float, default=0.5, help="Prior temperature")
    parser.add_argument(
        "--solver",
        type=str,
        default="midpoint",
        choices=["midpoint", "rk4", "euler"],
        help="Numerical solver",
    )
    parser.add_argument("--nfe", type=int, default=32, help="Number of function evaluations")
    parser.add_argument("--delay-ms", type=float, default=20.0, help="Dereverb tail delay in milliseconds")
    parser.add_argument("--decay-ms", type=float, default=180.0, help="Dereverb decay window in milliseconds")
    parser.add_argument("--reduction", type=float, default=0.72, help="Late-tail reduction strength")
    parser.add_argument("--gain-floor", type=float, default=0.16, help="Minimum spectral gain floor")
    parser.add_argument("--time-smoothing", type=float, default=0.72, help="Temporal smoothing for the gain curve")
    parser.add_argument(
        "--dereverb-method",
        type=str,
        default="wpe",
        choices=["wpe", "spectral"],
        help="Dereverb method to apply before Resemble Enhance",
    )
    parser.add_argument("--wpe-taps", type=int, default=10, help="Number of delayed prediction taps for WPE")
    parser.add_argument("--wpe-delay", type=int, default=3, help="Delay frames before the WPE predictor starts")
    parser.add_argument("--wpe-iterations", type=int, default=2, help="Number of WPE refinement passes")
    return parser


def _default_run_dir() -> Path | None:
    package_root = Path(resemble_enhance.__file__).resolve().parent
    run_dir = package_root / "model_repo" / "enhancer_stage2"
    weights = run_dir / "ds" / "G" / "default" / "mp_rank_00_model_states.pt"
    return run_dir if weights.exists() else None


def main() -> None:
    args = build_parser().parse_args()
    run_dir = args.run_dir or _default_run_dir()
    input_paths = sorted(args.in_dir.glob(f"**/*{args.suffix}"))
    if not input_paths:
        raise SystemExit(f"No {args.suffix} files found in {args.in_dir}")

    started = time.perf_counter()
    for input_path in input_paths:
        output_path = args.out_dir / input_path.relative_to(args.in_dir)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        waveform, sample_rate = torchaudio.load(str(input_path))
        mono = waveform.mean(0).cpu().numpy().astype(np.float32, copy=False)
        if args.dereverb_method == "wpe":
            dereverbed = wpe_dereverb(
                mono,
                sample_rate,
                taps=args.wpe_taps,
                delay=args.wpe_delay,
                iterations=args.wpe_iterations,
            )
        else:
            dereverbed = suppress_late_reverb(
                mono,
                sample_rate,
                delay_ms=args.delay_ms,
                decay_ms=args.decay_ms,
                reduction=args.reduction,
                gain_floor=args.gain_floor,
                time_smoothing=args.time_smoothing,
            )
        dereverbed_tensor = torch.from_numpy(dereverbed)
        enhanced, enhanced_sr = enhance(
            dwav=dereverbed_tensor,
            sr=sample_rate,
            device=args.device,
            nfe=args.nfe,
            solver=args.solver,
            lambd=args.lambd,
            tau=args.tau,
            run_dir=run_dir,
        )
        torchaudio.save(str(output_path), enhanced[None], enhanced_sr)

    elapsed = time.perf_counter() - started
    print(f"Studio cleanup done. {len(input_paths)} file(s) processed in {elapsed:.2f}s")


if __name__ == "__main__":
    main()
