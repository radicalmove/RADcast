"""Distributed worker queue manager for offloaded RADcast enhancement jobs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from radcast.manifests import ManifestStore
from radcast.models import (
    JobRecord,
    JobStatus,
    OutputFormat,
    OutputMetadata,
    WorkerCapability,
    WorkerEnhanceEnqueueRequest,
    WorkerJobCompleteRequest,
    WorkerJobFailRequest,
    WorkerJobProgressRequest,
    WorkerPullRequest,
    WorkerQueuedJob,
    WorkerRegisterRequest,
    WorkerRegisterResponse,
    WorkerSummary,
)
from radcast.project import ProjectManager
from radcast.services.enhance import current_audio_tuning_label


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _slugify_filename(name: str) -> str:
    safe = "".join(ch for ch in name if ch.isalnum() or ch in {"-", "_", "."}).strip(".")
    return safe or "source_audio.wav"


_UNSET = object()


class WorkerManager:
    def __init__(
        self,
        *,
        projects_root: Path,
        worker_secret: str,
        invite_max_age_seconds: int = 86400,
    ):
        self.projects_root = Path(projects_root)
        self.project_manager = ProjectManager(self.projects_root)
        self.worker_secret = worker_secret
        self.invite_max_age_seconds = invite_max_age_seconds

        self.worker_dir = self.projects_root / "_worker"
        self.workers_path = self.worker_dir / "workers.json"
        self.jobs_path = self.worker_dir / "jobs.json"
        self.worker_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._ensure_files()

    def _ensure_files(self) -> None:
        for path in (self.workers_path, self.jobs_path):
            if not path.exists():
                path.write_text("[]", encoding="utf-8")

    def _read_list(self, path: Path) -> list[dict[str, Any]]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _write_list(self, path: Path, payload: list[dict[str, Any]]) -> None:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _invite_serializer(self) -> URLSafeTimedSerializer:
        return URLSafeTimedSerializer(self.worker_secret, salt="radcast-worker-invite-v1")

    def issue_invite_token(self, capabilities: list[WorkerCapability] | None = None) -> str:
        payload = {
            "capabilities": [cap.value for cap in (capabilities or [WorkerCapability.ENHANCE])],
            "issued_at": _now_iso(),
        }
        return self._invite_serializer().dumps(payload)

    def register_worker(self, req: WorkerRegisterRequest) -> WorkerRegisterResponse:
        try:
            invite_payload = self._invite_serializer().loads(
                req.invite_token,
                max_age=self.invite_max_age_seconds,
            )
        except SignatureExpired as exc:
            raise ValueError("invite token expired") from exc
        except BadSignature as exc:
            raise ValueError("invalid invite token") from exc

        allowed = set(invite_payload.get("capabilities") or [WorkerCapability.ENHANCE.value])
        requested = [cap.value for cap in req.capabilities]
        capabilities = [cap for cap in requested if cap in allowed]
        if not capabilities:
            raise ValueError("worker capabilities do not match invite token")

        worker_id = f"wrk_{uuid.uuid4().hex[:10]}"
        api_key = secrets.token_urlsafe(32)
        now = _now_iso()
        record = {
            "worker_id": worker_id,
            "worker_name": req.worker_name,
            "capabilities": capabilities,
            "status": "active",
            "created_at": now,
            "last_seen_at": now,
            "api_key_hash": _hash_key(api_key),
        }

        with self._lock:
            workers = self._read_list(self.workers_path)
            workers.append(record)
            self._write_list(self.workers_path, workers)

        return WorkerRegisterResponse(worker_id=worker_id, api_key=api_key, poll_interval_seconds=5)

    def _authenticate_worker(self, req: WorkerPullRequest) -> dict[str, Any]:
        workers = self._read_list(self.workers_path)
        for worker in workers:
            if worker.get("worker_id") != req.worker_id:
                continue
            expected_hash = worker.get("api_key_hash", "")
            if not hmac.compare_digest(expected_hash, _hash_key(req.api_key)):
                break
            worker["last_seen_at"] = _now_iso()
            self._write_list(self.workers_path, workers)
            return worker
        raise PermissionError("invalid worker credentials")

    def list_workers(self) -> list[WorkerSummary]:
        workers = self._read_list(self.workers_path)
        summaries: list[WorkerSummary] = []
        for worker in workers:
            summaries.append(
                WorkerSummary(
                    worker_id=str(worker.get("worker_id") or ""),
                    worker_name=str(worker.get("worker_name") or worker.get("worker_id") or ""),
                    capabilities=[WorkerCapability(cap) for cap in worker.get("capabilities", [])],
                    status=str(worker.get("status") or "active"),
                    last_seen_at=worker.get("last_seen_at"),
                    created_at=str(worker.get("created_at") or _now_iso()),
                )
            )
        return summaries

    def enqueue_enhance_job(self, req: WorkerEnhanceEnqueueRequest) -> str:
        paths = self.project_manager.ensure_project(req.project_id)
        store = ManifestStore(paths.manifests)
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        now = _now_iso()

        store.upsert_job(
            JobRecord(
                id=job_id,
                project_id=req.project_id,
                status=JobStatus.QUEUED,
                stage="queued_remote",
                progress=0.0,
                logs=[f"{now} queued for worker execution"],
            )
        )

        queue_entry = {
            "job_id": job_id,
            "project_id": req.project_id,
            "status": "queued",
            "type": "enhance",
            "required_capabilities": [WorkerCapability.ENHANCE.value],
            "assigned_worker_id": None,
            "created_at": now,
            "updated_at": now,
            "payload": req.model_dump(mode="json"),
            "error": None,
        }

        with self._lock:
            jobs = self._read_list(self.jobs_path)
            jobs.append(queue_entry)
            self._write_list(self.jobs_path, jobs)

        return job_id

    def cancel_project_jobs(self, project_id: str, *, reason: str) -> list[str]:
        cancelled: list[str] = []
        with self._lock:
            jobs = self._read_list(self.jobs_path)
            changed = False
            for entry in jobs:
                if entry.get("project_id") != project_id:
                    continue
                if entry.get("status") not in {"queued", "running", "fallback_local"}:
                    continue
                entry["status"] = "cancelled"
                entry["error"] = reason
                entry["updated_at"] = _now_iso()
                cancelled.append(str(entry.get("job_id") or ""))
                changed = True
            if changed:
                self._write_list(self.jobs_path, jobs)

        for job_id in cancelled:
            if not job_id:
                continue
            self._update_job_manifest(
                project_id=project_id,
                job_id=job_id,
                status=JobStatus.CANCELLED,
                stage="cancelled",
                progress=0.0,
                error=reason,
                log=reason,
            )
        return [job_id for job_id in cancelled if job_id]

    def claim_job_for_local_fallback(
        self,
        job_id: str,
        *,
        reason: str,
        allowed_statuses: set[str] | None = None,
    ) -> WorkerEnhanceEnqueueRequest | None:
        permitted_statuses = allowed_statuses or {"queued", "running"}
        with self._lock:
            jobs = self._read_list(self.jobs_path)
            entry = next((item for item in jobs if item.get("job_id") == job_id), None)
            if not entry or entry.get("status") not in permitted_statuses:
                return None

            entry["status"] = "fallback_local"
            entry["assigned_worker_id"] = "local-fallback"
            entry["error"] = reason
            entry["updated_at"] = _now_iso()
            self._write_list(self.jobs_path, jobs)

        self._update_job_manifest(
            project_id=str(entry["project_id"]),
            job_id=job_id,
            status=JobStatus.RUNNING,
            stage="fallback_local",
            progress=0.08,
            log=reason,
        )
        return WorkerEnhanceEnqueueRequest(**entry["payload"])

    def cancel_queued_job(self, job_id: str, *, reason: str) -> bool:
        with self._lock:
            jobs = self._read_list(self.jobs_path)
            entry = next((item for item in jobs if item.get("job_id") == job_id), None)
            if not entry or entry.get("status") != "queued":
                return False
            entry["status"] = "cancelled"
            entry["error"] = reason
            entry["updated_at"] = _now_iso()
            self._write_list(self.jobs_path, jobs)

        self._update_job_manifest(
            project_id=str(entry["project_id"]),
            job_id=job_id,
            status=JobStatus.CANCELLED,
            stage="cancelled",
            progress=0.0,
            error=reason,
            log=reason,
        )
        return True

    def pull_job(self, req: WorkerPullRequest) -> WorkerQueuedJob | None:
        with self._lock:
            worker = self._authenticate_worker(req)
            jobs = self._read_list(self.jobs_path)
            changed = False
            for entry in jobs:
                if entry.get("status") != "queued":
                    continue
                try:
                    self.project_manager.ensure_project(str(entry.get("project_id") or ""))
                except FileNotFoundError:
                    entry["status"] = "cancelled"
                    entry["error"] = "project no longer exists"
                    entry["updated_at"] = _now_iso()
                    changed = True
                    continue
                required = set(entry.get("required_capabilities") or [])
                caps = set(worker.get("capabilities") or [])
                if not required.issubset(caps):
                    continue
                entry["status"] = "running"
                entry["assigned_worker_id"] = req.worker_id
                entry["updated_at"] = _now_iso()
                self._write_list(self.jobs_path, jobs)
                self._update_job_manifest(
                    project_id=str(entry["project_id"]),
                    job_id=str(entry["job_id"]),
                    status=JobStatus.RUNNING,
                    stage="worker_running",
                    progress=0.18,
                    log=f"worker {req.worker_id} started processing",
                )
                return WorkerQueuedJob(
                    job_id=str(entry["job_id"]),
                    project_id=str(entry["project_id"]),
                    type="enhance",
                    payload=dict(entry["payload"]),
                )
            if changed:
                self._write_list(self.jobs_path, jobs)
        return None

    def complete_job(self, job_id: str, req: WorkerJobCompleteRequest) -> str:
        pull_req = WorkerPullRequest(worker_id=req.worker_id, api_key=req.api_key)
        with self._lock:
            self._authenticate_worker(pull_req)
            jobs = self._read_list(self.jobs_path)
            entry = next((item for item in jobs if item.get("job_id") == job_id), None)
            if not entry:
                raise FileNotFoundError(f"worker job not found: {job_id}")
            if entry.get("assigned_worker_id") != req.worker_id or entry.get("status") != "running":
                return "ignored"
            entry["status"] = "completed"
            entry["updated_at"] = _now_iso()
            self._write_list(self.jobs_path, jobs)

        payload = WorkerEnhanceEnqueueRequest(**entry["payload"])
        paths = self.project_manager.ensure_project(payload.project_id)
        store = ManifestStore(paths.manifests)

        output_suffix = req.output_format.value
        output_path = paths.assets_enhanced_audio / f"{payload.output_name}.{output_suffix}"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(req.output_audio_b64.encode("utf-8")))

        input_filename = _slugify_filename(payload.input_audio_filename)
        input_path = paths.assets_source_audio / f"{payload.output_name}_{input_filename}"
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_bytes(base64.b64decode(payload.input_audio_b64.encode("utf-8")))

        metadata = OutputMetadata(
            output_file=output_path,
            input_file=input_path,
            duration_seconds=req.duration_seconds,
            output_format=OutputFormat(req.output_format),
            enhancement_model=payload.enhancement_model,
            audio_tuning_label=current_audio_tuning_label(),
            project_id=payload.project_id,
            job_id=job_id,
        )
        metadata_path = paths.manifests / f"{payload.output_name}.metadata.json"
        store.write_output_file(metadata_path, metadata)
        store.append_output(metadata)

        outputs = {
            "audio_path": str(output_path),
            "metadata_path": str(metadata_path),
        }
        self._update_job_manifest(
            project_id=payload.project_id,
            job_id=job_id,
            status=JobStatus.COMPLETED,
            stage="completed",
            progress=1.0,
            outputs=outputs,
            log=f"worker {req.worker_id} completed job",
        )
        return "completed"

    def progress_job(self, job_id: str, req: WorkerJobProgressRequest) -> str:
        pull_req = WorkerPullRequest(worker_id=req.worker_id, api_key=req.api_key)
        with self._lock:
            self._authenticate_worker(pull_req)
            jobs = self._read_list(self.jobs_path)
            entry = next((item for item in jobs if item.get("job_id") == job_id), None)
            if not entry:
                raise FileNotFoundError(f"worker job not found: {job_id}")
            if entry.get("assigned_worker_id") != req.worker_id or entry.get("status") != "running":
                return "ignored"
            entry["updated_at"] = _now_iso()
            self._write_list(self.jobs_path, jobs)

        detail = (req.detail or "").strip() or None
        stage = self._progress_stage_for_update(req.stage, detail)
        self._update_job_manifest(
            project_id=str(entry["project_id"]),
            job_id=job_id,
            status=JobStatus.RUNNING,
            stage=stage,
            progress=req.progress,
            eta_seconds=req.eta_seconds if req.eta_seconds is not None else _UNSET,
            log=detail,
        )
        return "running"

    @staticmethod
    def _progress_stage_for_update(stage: str | None, detail: str | None) -> str:
        normalized = str(stage or "").strip().lower()
        if normalized in {"queued_remote", "worker_running", "prepare", "enhance", "finalize"}:
            return normalized
        lower_detail = str(detail or "").strip().lower()
        if lower_detail.startswith("loading enhancement runtime"):
            return "prepare"
        if lower_detail.startswith("enhancing audio"):
            return "enhance"
        if lower_detail.startswith("saving enhanced audio"):
            return "finalize"
        return "worker_running"

    def fail_job(self, job_id: str, req: WorkerJobFailRequest) -> str:
        pull_req = WorkerPullRequest(worker_id=req.worker_id, api_key=req.api_key)
        with self._lock:
            self._authenticate_worker(pull_req)
            jobs = self._read_list(self.jobs_path)
            entry = next((item for item in jobs if item.get("job_id") == job_id), None)
            if not entry:
                raise FileNotFoundError(f"worker job not found: {job_id}")
            if entry.get("assigned_worker_id") != req.worker_id or entry.get("status") != "running":
                return "ignored"
            entry["status"] = "failed"
            entry["error"] = req.error
            entry["updated_at"] = _now_iso()
            self._write_list(self.jobs_path, jobs)

        self._update_job_manifest(
            project_id=str(entry["project_id"]),
            job_id=job_id,
            status=JobStatus.FAILED,
            stage="failed",
            progress=1.0,
            error=req.error,
            log=f"worker {req.worker_id} failed job: {req.error}",
        )
        return "failed"

    def _update_job_manifest(
        self,
        *,
        project_id: str,
        job_id: str,
        status: JobStatus,
        stage: str,
        progress: float,
        eta_seconds: int | None | object = _UNSET,
        error: str | None = None,
        outputs: dict[str, Any] | None = None,
        log: str | None = None,
    ) -> None:
        try:
            paths = self.project_manager.ensure_project(project_id)
        except FileNotFoundError:
            return
        store = ManifestStore(paths.manifests)
        payload = store.get_job(job_id)
        job = JobRecord(**payload) if payload else JobRecord(id=job_id, project_id=project_id, status=status, stage=stage)
        job.status = status
        job.stage = stage
        job.progress = max(0.0, min(1.0, progress))
        if eta_seconds is not _UNSET:
            job.eta_seconds = None if eta_seconds is None else max(0, int(eta_seconds))
        if error is not None:
            job.error = error
        if outputs is not None:
            job.outputs = outputs
        if log:
            previous = ""
            if job.logs:
                previous = job.logs[-1].split(" ", 1)[1] if " " in job.logs[-1] else job.logs[-1]
            if log != previous:
                job.logs.append(f"{_now_iso()} {log}")
        job.updated_at = datetime.now(timezone.utc)
        store.upsert_job(job)
