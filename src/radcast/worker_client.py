"""Worker daemon for distributed RADcast enhancement jobs."""

from __future__ import annotations

import argparse
import base64
import json
import logging
import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import requests

from radcast.exceptions import JobCancelledError
from radcast.models import OutputFormat, WorkerEnhanceEnqueueRequest
from radcast.progress import (
    estimate_caption_seconds,
    estimate_speech_cleanup_seconds,
    extend_eta_with_postprocess,
    map_postprocess_stage_progress,
    map_worker_stage_progress,
)
from radcast.services.enhance import EnhanceService
from radcast.services.speech_cleanup import SpeechCleanupService
from radcast.utils.audio import probe_duration_seconds

LOG = logging.getLogger("radcast.worker")


class WorkerClient:
    def __init__(
        self,
        *,
        server_url: str,
        config_path: Path,
        worker_name: str,
        invite_token: str | None,
        poll_seconds: int,
    ):
        self.server_url = server_url.rstrip("/")
        self.config_path = config_path
        self.worker_name = worker_name
        self.invite_token = invite_token
        self.poll_seconds = poll_seconds

        self.worker_id: str | None = None
        self.api_key: str | None = None

        self.session = requests.Session()
        self.enhance_service = EnhanceService()
        self.speech_cleanup_service = SpeechCleanupService()

    def _post_json(self, path: str, payload: dict[str, Any], timeout: int = 120) -> dict[str, Any]:
        url = f"{self.server_url}{path}"
        response = self.session.post(url, json=payload, timeout=timeout)
        if response.status_code >= 400:
            raise RuntimeError(f"{response.status_code} {url} -> {response.text[:400]}")
        if not response.content:
            return {}
        return response.json()

    def _load_config(self) -> None:
        if not self.config_path.exists():
            return
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.worker_id = payload.get("worker_id")
        self.api_key = payload.get("api_key")

    def _save_config(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(
                {
                    "server_url": self.server_url,
                    "worker_id": self.worker_id,
                    "api_key": self.api_key,
                    "worker_name": self.worker_name,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def ensure_registered(self) -> None:
        self._load_config()
        if self.worker_id and self.api_key and not self.invite_token:
            LOG.info("reusing worker credentials worker_id=%s", self.worker_id)
            return
        if not self.invite_token:
            raise RuntimeError("Worker is not registered. Provide --invite-token or reuse an existing config file.")
        response = self._post_json(
            "/workers/register",
            {
                "invite_token": self.invite_token,
                "worker_name": self.worker_name,
                "capabilities": ["enhance"],
            },
        )
        self.worker_id = response["worker_id"]
        self.api_key = response["api_key"]
        self._save_config()
        LOG.info("registered worker worker_id=%s name=%s", self.worker_id, self.worker_name)

    def run(self, *, once: bool = False) -> None:
        self.ensure_registered()
        assert self.worker_id and self.api_key
        LOG.info("worker loop starting worker_id=%s server=%s poll_seconds=%s", self.worker_id, self.server_url, self.poll_seconds)
        while True:
            pull_response = self._post_json(
                "/workers/pull",
                {"worker_id": self.worker_id, "api_key": self.api_key},
                timeout=180,
            )
            job = pull_response.get("job")
            if not job:
                LOG.info("no job available; continuing to poll")
                if once:
                    return
                time.sleep(self.poll_seconds)
                continue

            job_id = str(job["job_id"])
            payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
            LOG.info(
                "claimed job job_id=%s project_id=%s enhancement_model=%s output_format=%s filename=%s",
                job_id,
                job.get("project_id"),
                payload.get("enhancement_model"),
                payload.get("output_format"),
                payload.get("input_audio_filename"),
            )
            try:
                complete_payload = self._process_enhance_job(job_id, payload)
                complete_payload.update({"worker_id": self.worker_id, "api_key": self.api_key})
                response = self._post_json(f"/workers/jobs/{job_id}/complete", complete_payload, timeout=1800)
                if str(response.get("status") or "").lower() in {"ignored", "cancelled"}:
                    LOG.info("job %s was cancelled or reassigned before completion acknowledgement", job_id)
                    if once:
                        return
                    continue
                LOG.info("completed job job_id=%s", job_id)
            except JobCancelledError:
                LOG.info("job cancelled on server while helper was processing job_id=%s", job_id)
            except Exception as exc:
                error_text = str(exc).strip() or f"{exc.__class__.__name__}: {exc!r}"
                LOG.exception("job failed job_id=%s error=%s", job_id, error_text)
                self._post_json(
                    f"/workers/jobs/{job_id}/fail",
                    {"worker_id": self.worker_id, "api_key": self.api_key, "error": error_text[:1800]},
                )
            if once:
                return

    def _post_progress_update(
        self,
        job_id: str,
        *,
        progress: float,
        stage: str | None = None,
        detail: str | None = None,
        eta_seconds: int | None = None,
    ) -> str | None:
        assert self.worker_id and self.api_key
        payload = {"worker_id": self.worker_id, "api_key": self.api_key, "progress": max(0.0, min(1.0, float(progress)))}
        if stage:
            payload["stage"] = stage
        if detail:
            payload["detail"] = detail
        if eta_seconds is not None:
            payload["eta_seconds"] = max(0, int(eta_seconds))
        try:
            response = self._post_json(f"/workers/jobs/{job_id}/progress", payload, timeout=60)
            return str(response.get("status") or "").strip().lower() or None
        except Exception:
            return None

    def _process_enhance_job(self, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = WorkerEnhanceEnqueueRequest(**payload)
        with tempfile.TemporaryDirectory(prefix="radcast_worker_") as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / req.input_audio_filename
            input_path.write_bytes(base64.b64decode(req.input_audio_b64.encode("utf-8")))
            cleanup_requested = req.speech_cleanup_requested()
            caption_requested = req.caption_requested()
            postprocess_requested = cleanup_requested or caption_requested
            postprocess_available = False
            caption_generation_available = False
            cleanup_eta_seconds = None
            caption_eta_seconds = None
            input_duration_seconds = None
            if postprocess_requested:
                postprocess_available, _cleanup_detail = self.speech_cleanup_service.capability_status()
                caption_generation_available = callable(getattr(self.speech_cleanup_service, "generate_caption_file", None))
                try:
                    input_duration_seconds = probe_duration_seconds(input_path)
                    if cleanup_requested:
                        cleanup_eta_seconds = estimate_speech_cleanup_seconds(
                            input_duration_seconds,
                            remove_filler_words=req.remove_filler_words,
                            filler_removal_mode=req.filler_removal_mode,
                        )
                    if caption_requested:
                        caption_eta_seconds = estimate_caption_seconds(input_duration_seconds)
                except Exception:
                    cleanup_eta_seconds = None
                    caption_eta_seconds = None

            stage_durations_seconds: dict[str, float] = {}
            progress_state = {"progress": 0.18, "stage": "worker_running", "detail": None, "eta_seconds": None}
            progress_lock = threading.Lock()
            stop_heartbeat = threading.Event()
            cancel_requested = threading.Event()

            def mark_cancel_requested() -> None:
                if cancel_requested.is_set():
                    return
                cancel_requested.set()
                self.enhance_service.cancel(job_id)

            def emit_progress(
                progress: float,
                *,
                stage: str | None = None,
                detail: str | None = None,
                eta_seconds: int | None = None,
            ) -> None:
                with progress_lock:
                    progress_state["progress"] = max(0.0, min(1.0, float(progress)))
                    progress_state["stage"] = stage or progress_state["stage"]
                    progress_state["detail"] = detail
                    progress_state["eta_seconds"] = None if eta_seconds is None else max(0, int(eta_seconds))
                status = self._post_progress_update(job_id, progress=progress, stage=stage, detail=detail, eta_seconds=eta_seconds)
                if status in {"ignored", "cancelled"}:
                    mark_cancel_requested()

            def heartbeat_worker() -> None:
                while not stop_heartbeat.wait(10):
                    with progress_lock:
                        progress = float(progress_state["progress"])
                        stage = str(progress_state["stage"] or "worker_running")
                        eta_seconds = progress_state["eta_seconds"]
                    status = self._post_progress_update(job_id, progress=progress, stage=stage, eta_seconds=eta_seconds)
                    if status in {"ignored", "cancelled"}:
                        mark_cancel_requested()
                        return

            heartbeat_thread = threading.Thread(target=heartbeat_worker, name="radcast-worker-heartbeat", daemon=True)
            heartbeat_thread.start()
            try:
                started_at = time.monotonic()
                cleanup_result = None
                caption_b64 = None

                def on_stage(stage: str, progress: float, detail: str, eta_seconds: int | None = None) -> None:
                    emit_progress(
                        map_worker_stage_progress(stage, progress, reserve_cleanup_band=postprocess_requested),
                        stage=stage,
                        detail=detail,
                        eta_seconds=extend_eta_with_postprocess(
                            eta_seconds,
                            cleanup_eta_seconds if cleanup_requested else None,
                            caption_eta_seconds if caption_requested else None,
                            reserve_postprocess_band=postprocess_requested and stage in {"prepare", "enhance", "finalize"},
                        ),
                    )

                output_base = tmp_path / req.output_name
                final_path = self.enhance_service.enhance(
                    job_id=job_id,
                    enhancement_model=req.enhancement_model,
                    input_audio_path=input_path,
                    output_format=req.output_format,
                    output_base_path=output_base,
                    on_stage=on_stage,
                    cancel_check=lambda: cancel_requested.is_set(),
                )
                if cancel_requested.is_set():
                    raise JobCancelledError("job cancelled")
                if cleanup_requested and postprocess_available:
                    cleanup_started_at = time.monotonic()
                    emit_progress(
                        map_postprocess_stage_progress(
                            0.0,
                            stage="cleanup",
                            cleanup_requested=True,
                            caption_requested=caption_requested,
                        ),
                        stage="cleanup",
                        detail="Applying speech cleanup on your local helper device.",
                        eta_seconds=max(
                            1,
                            int((cleanup_eta_seconds or 0) + (caption_eta_seconds or 0)),
                        ),
                    )
                    cleanup_result = self.speech_cleanup_service.cleanup_audio_file(
                        audio_path=final_path,
                        output_format=req.output_format,
                        max_silence_seconds=req.max_silence_seconds,
                        remove_filler_words=req.remove_filler_words,
                        filler_removal_mode=req.filler_removal_mode,
                        on_stage=lambda progress, detail, eta_seconds: emit_progress(
                            map_postprocess_stage_progress(
                                progress,
                                stage="cleanup",
                                cleanup_requested=True,
                                caption_requested=caption_requested,
                            ),
                            stage="cleanup",
                            detail=f"{detail} On your local helper device.",
                            eta_seconds=extend_eta_with_postprocess(
                                eta_seconds,
                                None,
                                caption_eta_seconds if caption_requested else None,
                                reserve_postprocess_band=caption_requested,
                            )
                            if eta_seconds is not None or caption_requested
                            else None,
                        ),
                        cancel_check=lambda: cancel_requested.is_set(),
                    )
                    stage_durations_seconds["cleanup"] = round(time.monotonic() - cleanup_started_at, 3)
                    emit_progress(
                        map_postprocess_stage_progress(
                            0.98,
                            stage="cleanup",
                            cleanup_requested=True,
                            caption_requested=caption_requested,
                        ),
                        stage="cleanup",
                        detail="Saving cleaned audio on your local helper device.",
                        eta_seconds=max(5, caption_eta_seconds or 5),
                    )
                elif cleanup_requested:
                    emit_progress(
                        map_worker_stage_progress("finalize", 0.96, reserve_cleanup_band=postprocess_requested),
                        stage="finalize",
                        detail="Uploading audio for server-side post-processing",
                        eta_seconds=max(8, int((cleanup_eta_seconds or 0) + (caption_eta_seconds or 0) or 8)),
                    )
                elif not caption_requested:
                    emit_progress(
                        map_worker_stage_progress("finalize", 0.96, reserve_cleanup_band=False),
                        stage="finalize",
                        detail="Saving enhanced audio",
                        eta_seconds=8,
                    )

                if cancel_requested.is_set():
                    raise JobCancelledError("job cancelled")

                if caption_requested and req.caption_format is not None and postprocess_available and caption_generation_available:
                    caption_started_at = time.monotonic()
                    emit_progress(
                        map_postprocess_stage_progress(
                            0.0,
                            stage="captions",
                            cleanup_requested=cleanup_requested,
                            caption_requested=True,
                        ),
                        stage="captions",
                        detail="Generating captions on your local helper device.",
                        eta_seconds=max(1, int(caption_eta_seconds or 1)),
                    )
                    caption_result = self.speech_cleanup_service.generate_caption_file(
                        audio_path=final_path,
                        caption_format=req.caption_format,
                        on_stage=lambda progress, detail, eta_seconds: emit_progress(
                            map_postprocess_stage_progress(
                                progress,
                                stage="captions",
                                cleanup_requested=cleanup_requested,
                                caption_requested=True,
                            ),
                            stage="captions",
                            detail=f"{detail} On your local helper device.",
                            eta_seconds=eta_seconds,
                        ),
                        cancel_check=lambda: cancel_requested.is_set(),
                    )
                    stage_durations_seconds["captions"] = round(time.monotonic() - caption_started_at, 3)
                    caption_b64 = base64.b64encode(caption_result.caption_path.read_bytes()).decode("utf-8")
                    emit_progress(
                        map_postprocess_stage_progress(
                            0.99,
                            stage="captions",
                            cleanup_requested=cleanup_requested,
                            caption_requested=True,
                        ),
                        stage="captions",
                        detail="Uploading audio and captions from your local helper device.",
                        eta_seconds=5,
                    )
                elif caption_requested:
                    emit_progress(
                        map_worker_stage_progress("finalize", 0.96, reserve_cleanup_band=postprocess_requested),
                        stage="finalize",
                        detail="Uploading audio for server-side caption generation",
                        eta_seconds=max(8, int((caption_eta_seconds or 0) or 8)),
                    )

                if cancel_requested.is_set():
                    raise JobCancelledError("job cancelled")
                stage_durations_seconds["total"] = round(time.monotonic() - started_at, 3)
                response = {
                    "output_audio_b64": base64.b64encode(final_path.read_bytes()).decode("utf-8"),
                    "output_format": OutputFormat(req.output_format).value,
                    "duration_seconds": probe_duration_seconds(final_path),
                    "cleanup_applied": bool(cleanup_result and cleanup_result.applied),
                    "cleanup_summary": cleanup_result.summary_text() if cleanup_result else None,
                    "stage_durations_seconds": stage_durations_seconds,
                }
                if caption_b64 is not None:
                    response["caption_b64"] = caption_b64
                return response
            finally:
                stop_heartbeat.set()
                heartbeat_thread.join(timeout=1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RADcast distributed worker")
    parser.add_argument("--server-url", required=True, help="RADcast server base URL")
    parser.add_argument("--invite-token", help="Invite token from /workers/invite")
    parser.add_argument("--worker-name", default=socket.gethostname())
    parser.add_argument(
        "--config-path",
        default=str(Path.home() / ".radcast" / "worker.json"),
        help="Path for worker credentials cache",
    )
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--once", action="store_true", help="Process at most one pull cycle")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", force=True)
    args = build_parser().parse_args()
    client = WorkerClient(
        server_url=args.server_url,
        config_path=Path(args.config_path),
        worker_name=args.worker_name,
        invite_token=args.invite_token,
        poll_seconds=max(1, args.poll_seconds),
    )
    client.run(once=args.once)


if __name__ == "__main__":
    main()
