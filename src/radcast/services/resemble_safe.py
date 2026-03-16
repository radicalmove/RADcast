"""DeepSpeed-free helpers for resemble-enhance inference wrappers."""

from __future__ import annotations

import sys
import types
import time
from functools import cache
from pathlib import Path
from typing import Any, Callable

import torch
import resemble_enhance
from resemble_enhance.inference import (
    inference as run_inference,
    inference_chunk as run_inference_chunk,
    merge_chunks as run_merge_chunks,
    remove_weight_norm_recursively,
)
from torchaudio.functional import resample


def _passthrough_decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
    return fn


class _TrainLoopStub:
    @staticmethod
    def get_running_loop() -> None:
        return None


def _install_stub_module(name: str, **attrs: Any) -> None:
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    for key, value in attrs.items():
        setattr(module, key, value)


@cache
def _install_resemble_runtime_stubs() -> None:
    _install_stub_module(
        "resemble_enhance.utils.distributed",
        global_leader_only=_passthrough_decorator,
        local_leader_only=_passthrough_decorator,
        is_global_leader=lambda: True,
        is_local_leader=lambda: True,
    )
    _install_stub_module(
        "resemble_enhance.utils.train_loop",
        TrainLoop=_TrainLoopStub,
        is_global_leader=lambda: True,
    )

    @cache
    def _load_denoiser(run_dir: Path | None, device: str):
        from resemble_enhance.denoiser.denoiser import Denoiser
        from resemble_enhance.denoiser.hparams import HParams as DenoiserHParams

        if run_dir is None:
            denoiser = Denoiser(DenoiserHParams())
        else:
            hp = DenoiserHParams.load(run_dir)
            denoiser = Denoiser(hp)
            path = run_dir / "ds" / "G" / "default" / "mp_rank_00_model_states.pt"
            state_dict = torch.load(path, map_location="cpu")["module"]
            denoiser.load_state_dict(state_dict)
        denoiser.eval()
        denoiser.to(device)
        return denoiser

    def _denoise(dwav, sr, run_dir, device):
        denoiser = _load_denoiser(run_dir, device)
        return run_inference(model=denoiser, dwav=dwav, sr=sr, device=device)

    _install_stub_module(
        "resemble_enhance.denoiser.inference",
        load_denoiser=_load_denoiser,
        denoise=_denoise,
    )


def _default_run_dir() -> Path | None:
    package_root = Path(resemble_enhance.__file__).resolve().parent
    run_dir = package_root / "model_repo" / "enhancer_stage2"
    weights = run_dir / "ds" / "G" / "default" / "mp_rank_00_model_states.pt"
    return run_dir if weights.exists() else None


@cache
def _enhancer_types():
    _install_resemble_runtime_stubs()
    from resemble_enhance.enhancer.enhancer import Enhancer
    from resemble_enhance.enhancer.hparams import HParams as EnhancerHParams

    return Enhancer, EnhancerHParams


@cache
def load_enhancer(run_dir: Path | None, device: str):
    Enhancer, EnhancerHParams = _enhancer_types()
    if run_dir is None:
        run_dir = _default_run_dir()
    if run_dir is None:
        raise FileNotFoundError("Resemble Enhance weights were not found.")

    hp = EnhancerHParams.load(run_dir)
    enhancer = Enhancer(hp)
    path = run_dir / "ds" / "G" / "default" / "mp_rank_00_model_states.pt"
    state_dict = torch.load(path, map_location="cpu")["module"]
    enhancer.load_state_dict(state_dict)
    enhancer.eval()
    enhancer.to(device)
    return enhancer


def enhance(
    *,
    dwav,
    sr: int,
    device: str,
    nfe: int = 32,
    solver: str = "midpoint",
    lambd: float = 0.5,
    tau: float = 0.5,
    run_dir: Path | None = None,
):
    enhancer = load_enhancer(run_dir, device)
    enhancer.configurate_(nfe=nfe, solver=solver, lambd=lambd, tau=tau)
    chunk_seconds, overlap_seconds = _chunk_settings_for_device(device)
    return _run_inference_with_progress(
        model=enhancer,
        dwav=dwav,
        sr=sr,
        device=device,
        chunk_seconds=chunk_seconds,
        overlap_seconds=overlap_seconds,
    )


def default_run_dir() -> Path | None:
    return _default_run_dir()


def denoise(*, dwav, sr: int, device: str, run_dir: Path | None = None):
    _install_resemble_runtime_stubs()
    module = sys.modules["resemble_enhance.denoiser.inference"]
    return module.denoise(dwav=dwav, sr=sr, run_dir=run_dir, device=device)


def _chunk_settings_for_device(device: str) -> tuple[float, float]:
    normalized = str(device or "").strip().lower()
    if normalized.startswith("cuda") or normalized == "mps":
        return (24.0, 1.0)
    return (12.0, 1.0)


def _run_inference_with_progress(
    *,
    model,
    dwav,
    sr: int,
    device: str,
    chunk_seconds: float,
    overlap_seconds: float,
):
    remove_weight_norm_recursively(model)
    hp = model.hp

    dwav = resample(
        dwav,
        orig_freq=sr,
        new_freq=hp.wav_rate,
        lowpass_filter_width=64,
        rolloff=0.9475937167399596,
        resampling_method="sinc_interp_kaiser",
        beta=14.769656459379492,
    )
    sr = hp.wav_rate

    if torch.cuda.is_available():
        torch.cuda.synchronize()

    started = time.perf_counter()
    chunk_length = max(1, int(sr * chunk_seconds))
    overlap_length = max(0, int(sr * overlap_seconds))
    hop_length = max(1, chunk_length - overlap_length)
    chunk_starts = list(range(0, dwav.shape[-1], hop_length))
    total_chunks = max(1, len(chunk_starts))

    print(f"RADCAST_ENHANCE_PROGRESS 0/{total_chunks}", flush=True)
    chunks = []
    for index, start in enumerate(chunk_starts, start=1):
        chunks.append(run_inference_chunk(model, dwav[start : start + chunk_length], sr, device))
        print(f"RADCAST_ENHANCE_PROGRESS {index}/{total_chunks}", flush=True)

    hwav = run_merge_chunks(chunks, chunk_length, hop_length, sr=sr, length=dwav.shape[-1])

    if torch.cuda.is_available():
        torch.cuda.synchronize()

    elapsed = time.perf_counter() - started
    print(f"RADCAST_ENHANCE_DONE elapsed={elapsed:.3f}s chunks={total_chunks}", flush=True)
    return hwav, sr
