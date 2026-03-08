"""Stable CLI wrapper around resemble-enhance.

The upstream resemble-enhance console entrypoint passes ``Path`` objects
directly into ``torchaudio.load()``, which breaks on the torchaudio build we
run on macOS. This wrapper keeps the same folder-in/folder-out contract but
coerces paths to plain strings before handing them to torchaudio.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import resemble_enhance
import torchaudio
from resemble_enhance.enhancer.inference import denoise, enhance


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Enhance audio with Resemble Enhance")
    parser.add_argument("in_dir", type=Path, help="Path to input audio folder")
    parser.add_argument("out_dir", type=Path, help="Output folder")
    parser.add_argument("--run_dir", type=Path, default=None, help="Optional model checkpoint folder")
    parser.add_argument("--suffix", type=str, default=".wav", help="Audio file suffix")
    parser.add_argument("--device", type=str, default="cpu", help="Execution device")
    parser.add_argument("--denoise_only", action="store_true", help="Only apply denoising")
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

        dwav, sr = torchaudio.load(str(input_path))
        dwav = dwav.mean(0)
        if args.denoise_only:
            hwav, sr = denoise(dwav=dwav, sr=sr, device=args.device, run_dir=run_dir)
        else:
            hwav, sr = enhance(
                dwav=dwav,
                sr=sr,
                device=args.device,
                nfe=args.nfe,
                solver=args.solver,
                lambd=args.lambd,
                tau=args.tau,
                run_dir=run_dir,
            )
        torchaudio.save(str(output_path), hwav[None], sr)

    elapsed = time.perf_counter() - started
    print(f"Enhancement done. {len(input_paths)} file(s) processed in {elapsed:.2f}s")


if __name__ == "__main__":
    main()
