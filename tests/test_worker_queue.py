from __future__ import annotations

import base64
import shutil
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from radcast.api import app
from radcast.exceptions import JobCancelledError
from radcast.models import FillerRemovalMode
from radcast.services.speech_cleanup import SpeechCleanupResult
from radcast.worker_client import WorkerClient


def test_worker_queue_round_trip_completes_job():
    client = TestClient(app)
    project_id = f"radcast-worker-{uuid.uuid4().hex[:8]}"
    sample_b64 = base64.b64encode(b"fake-wav-audio" * 8).decode("utf-8")
    from radcast import api as api_module

    original_is_model_available = api_module.enhance_service.is_model_available
    api_module.enhance_service.is_model_available = lambda _model: True

    try:
        created = client.post("/projects", json={"project_id": project_id})
        assert created.status_code == 200

        invite = client.post("/workers/invite", json={"capabilities": ["enhance"]})
        assert invite.status_code == 200
        token = invite.json()["invite_token"]

        register = client.post(
            "/workers/register",
            json={
                "invite_token": token,
                "worker_name": "test-worker",
                "capabilities": ["enhance"],
            },
        )
        assert register.status_code == 200
        worker_id = register.json()["worker_id"]
        api_key = register.json()["api_key"]

        queued = client.post(
            "/enhance/simple",
            json={
                "project_id": project_id,
                "input_audio_b64": sample_b64,
                "input_audio_filename": "lecture.wav",
                "output_format": "mp3",
                "enhancement_model": "deepfilternet",
            },
        )
        assert queued.status_code == 200
        job_id = queued.json()["job_id"]
        assert queued.json()["worker_mode"] is True

        pull = client.post("/workers/pull", json={"worker_id": worker_id, "api_key": api_key})
        assert pull.status_code == 200
        job = pull.json()["job"]
        assert job["job_id"] == job_id
        assert job["type"] == "enhance"
        assert job["payload"]["enhancement_model"] == "deepfilternet"

        progress = client.post(
            f"/workers/jobs/{job_id}/progress",
            json={
                "worker_id": worker_id,
                "api_key": api_key,
                "progress": 0.62,
                "stage": "enhance",
                "detail": "Enhancing audio",
                "eta_seconds": 24,
            },
        )
        assert progress.status_code == 200
        assert progress.json()["status"] == "running"

        running = client.get(f"/jobs/{job_id}", params={"project_id": project_id})
        assert running.status_code == 200
        running_payload = running.json()
        assert running_payload["status"] == "running"
        assert running_payload["stage"] == "enhance"
        assert running_payload["eta_seconds"] == 24

        complete = client.post(
            f"/workers/jobs/{job_id}/complete",
            json={
                "worker_id": worker_id,
                "api_key": api_key,
                "output_audio_b64": base64.b64encode(b"fake-mp3" * 8).decode("utf-8"),
                "output_format": "mp3",
                "duration_seconds": 3.4,
                "stage_durations_seconds": {"total": 7.1},
            },
        )
        assert complete.status_code == 200
        assert complete.json()["status"] == "completed"

        polled = client.get(f"/jobs/{job_id}", params={"project_id": project_id})
        assert polled.status_code == 200
        payload = polled.json()
        assert payload["status"] == "completed"
        assert payload["outputs"]["audio_path"].endswith(".mp3")
    finally:
        api_module.enhance_service.is_model_available = original_is_model_available
        for path in Path("projects").glob(f"*__{project_id}"):
            if path.exists():
                shutil.rmtree(path)
        project_root = Path("projects") / project_id
        if project_root.exists():
            shutil.rmtree(project_root)


def test_worker_completion_applies_server_side_speech_cleanup(monkeypatch):
    client = TestClient(app)
    project_id = f"radcast-worker-{uuid.uuid4().hex[:8]}"
    sample_b64 = base64.b64encode(b"fake-wav-audio" * 8).decode("utf-8")
    from radcast import api as api_module

    original_is_model_available = api_module.enhance_service.is_model_available
    captured: dict[str, object] = {}

    def fake_cleanup(**kwargs):
        captured["max_silence_seconds"] = kwargs.get("max_silence_seconds")
        captured["remove_filler_words"] = kwargs.get("remove_filler_words")
        captured["filler_removal_mode"] = kwargs.get("filler_removal_mode")
        return SpeechCleanupResult(applied=True, removed_pause_count=1, removed_filler_count=1, duration_seconds=2.1)

    monkeypatch.setattr("radcast.worker_manager.speech_cleanup_service.cleanup_audio_file", fake_cleanup)
    api_module.enhance_service.is_model_available = lambda _model: True

    try:
        created = client.post("/projects", json={"project_id": project_id})
        assert created.status_code == 200

        invite = client.post("/workers/invite", json={"capabilities": ["enhance"]})
        assert invite.status_code == 200
        token = invite.json()["invite_token"]

        register = client.post(
            "/workers/register",
            json={
                "invite_token": token,
                "worker_name": "test-worker",
                "capabilities": ["enhance"],
            },
        )
        assert register.status_code == 200
        worker_id = register.json()["worker_id"]
        api_key = register.json()["api_key"]

        queued = client.post(
            "/enhance/simple",
            json={
                "project_id": project_id,
                "input_audio_b64": sample_b64,
                "input_audio_filename": "lecture.wav",
                "output_format": "mp3",
                "enhancement_model": "deepfilternet",
                "max_silence_seconds": 0.5,
                "remove_filler_words": True,
                "filler_removal_mode": "normal",
            },
        )
        assert queued.status_code == 200
        job_id = queued.json()["job_id"]

        pull = client.post("/workers/pull", json={"worker_id": worker_id, "api_key": api_key})
        assert pull.status_code == 200

        complete = client.post(
            f"/workers/jobs/{job_id}/complete",
            json={
                "worker_id": worker_id,
                "api_key": api_key,
                "output_audio_b64": base64.b64encode(b"fake-mp3" * 8).decode("utf-8"),
                "output_format": "mp3",
                "duration_seconds": 3.4,
                "cleanup_applied": False,
                "stage_durations_seconds": {"total": 7.1},
            },
        )
        assert complete.status_code == 200
        assert complete.json()["status"] == "accepted"
        assert captured == {
            "max_silence_seconds": 0.5,
            "remove_filler_words": True,
            "filler_removal_mode": FillerRemovalMode.NORMAL,
        }
        for _ in range(20):
            payload = client.get(f"/jobs/{job_id}", params={"project_id": project_id}).json()
            if payload["status"] == "completed":
                break
            time.sleep(0.05)
        else:
            raise AssertionError("worker cleanup finalization did not complete in time")
    finally:
        api_module.enhance_service.is_model_available = original_is_model_available
        for path in Path("projects").glob(f"*__{project_id}"):
            if path.exists():
                shutil.rmtree(path)
        project_root = Path("projects") / project_id
        if project_root.exists():
            shutil.rmtree(project_root)


def test_worker_completion_skips_server_cleanup_when_helper_already_applied_it(monkeypatch):
    client = TestClient(app)
    project_id = f"radcast-worker-{uuid.uuid4().hex[:8]}"
    sample_b64 = base64.b64encode(b"fake-wav-audio" * 8).decode("utf-8")
    from radcast import api as api_module

    original_is_model_available = api_module.enhance_service.is_model_available

    def fail_cleanup(**kwargs):
        raise AssertionError("server-side cleanup should not run when helper already applied it")

    monkeypatch.setattr("radcast.worker_manager.speech_cleanup_service.cleanup_audio_file", fail_cleanup)
    api_module.enhance_service.is_model_available = lambda _model: True

    try:
        created = client.post("/projects", json={"project_id": project_id})
        assert created.status_code == 200

        invite = client.post("/workers/invite", json={"capabilities": ["enhance"]})
        token = invite.json()["invite_token"]
        register = client.post(
            "/workers/register",
            json={"invite_token": token, "worker_name": "test-worker", "capabilities": ["enhance"]},
        )
        worker_id = register.json()["worker_id"]
        api_key = register.json()["api_key"]

        queued = client.post(
            "/enhance/simple",
            json={
                "project_id": project_id,
                "input_audio_b64": sample_b64,
                "input_audio_filename": "lecture.wav",
                "output_format": "mp3",
                "enhancement_model": "deepfilternet",
                "max_silence_seconds": 0.5,
                "remove_filler_words": True,
                "filler_removal_mode": "aggressive",
            },
        )
        job_id = queued.json()["job_id"]

        pull = client.post("/workers/pull", json={"worker_id": worker_id, "api_key": api_key})
        assert pull.status_code == 200

        complete = client.post(
            f"/workers/jobs/{job_id}/complete",
            json={
                "worker_id": worker_id,
                "api_key": api_key,
                "output_audio_b64": base64.b64encode(b"fake-mp3" * 8).decode("utf-8"),
                "output_format": "mp3",
                "duration_seconds": 2.1,
                "cleanup_applied": True,
                "cleanup_summary": "Shortened 1 long pause, removed 1 filler word.",
                "stage_durations_seconds": {"total": 7.1, "cleanup": 1.2},
            },
        )
        assert complete.status_code == 200
        assert complete.json()["status"] == "completed"

        payload = client.get(f"/jobs/{job_id}", params={"project_id": project_id}).json()
        assert payload["status"] == "completed"
        assert payload["logs"][-1].endswith("Shortened 1 long pause, removed 1 filler word.")
    finally:
        api_module.enhance_service.is_model_available = original_is_model_available
        for path in Path("projects").glob(f"*__{project_id}"):
            if path.exists():
                shutil.rmtree(path)
        project_root = Path("projects") / project_id
        if project_root.exists():
            shutil.rmtree(project_root)


def test_cancel_endpoint_marks_running_worker_job_cancelled():
    client = TestClient(app)
    project_id = f"radcast-worker-{uuid.uuid4().hex[:8]}"
    sample_b64 = base64.b64encode(b"fake-wav-audio" * 8).decode("utf-8")
    from radcast import api as api_module

    original_is_model_available = api_module.enhance_service.is_model_available
    api_module.enhance_service.is_model_available = lambda _model: True

    try:
        created = client.post("/projects", json={"project_id": project_id})
        assert created.status_code == 200

        invite = client.post("/workers/invite", json={"capabilities": ["enhance"]})
        token = invite.json()["invite_token"]
        register = client.post(
            "/workers/register",
            json={"invite_token": token, "worker_name": "test-worker", "capabilities": ["enhance"]},
        )
        worker_id = register.json()["worker_id"]
        api_key = register.json()["api_key"]

        queued = client.post(
            "/enhance/simple",
            json={
                "project_id": project_id,
                "input_audio_b64": sample_b64,
                "input_audio_filename": "lecture.wav",
                "output_format": "mp3",
                "enhancement_model": "deepfilternet",
            },
        )
        job_id = queued.json()["job_id"]

        pull = client.post("/workers/pull", json={"worker_id": worker_id, "api_key": api_key})
        assert pull.status_code == 200

        cancelled = client.post(f"/jobs/{job_id}/cancel", params={"project_id": project_id})
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancel_requested"

        progress = client.post(
            f"/workers/jobs/{job_id}/progress",
            json={"worker_id": worker_id, "api_key": api_key, "progress": 0.4, "stage": "enhance"},
        )
        assert progress.status_code == 200
        assert progress.json()["status"] == "ignored"
    finally:
        api_module.enhance_service.is_model_available = original_is_model_available
        for path in Path("projects").glob(f"*__{project_id}"):
            if path.exists():
                shutil.rmtree(path)
        project_root = Path("projects") / project_id
        if project_root.exists():
            shutil.rmtree(project_root)


def test_worker_client_cancels_local_run_when_server_ignores_progress(monkeypatch, tmp_path: Path):
    client = WorkerClient(
        server_url="http://example.invalid",
        config_path=tmp_path / "worker.json",
        worker_name="test-worker",
        invite_token=None,
        poll_seconds=1,
    )
    cancel_calls: list[str] = []

    class FakeEnhanceService:
        def cancel(self, job_id: str) -> None:
            cancel_calls.append(job_id)

        def enhance(self, **kwargs):
            kwargs["on_stage"]("prepare", 0.12, "Preparing enhancement", 12)
            deadline = time.monotonic() + 0.3
            while time.monotonic() < deadline:
                if kwargs["cancel_check"]():
                    raise JobCancelledError("job cancelled")
                time.sleep(0.01)
            raise AssertionError("cancel_check was not triggered")

    client.enhance_service = FakeEnhanceService()
    monkeypatch.setattr("radcast.worker_client.probe_duration_seconds", lambda _path: 5.0)
    progress_calls = {"count": 0}

    def fake_post_progress_update(*args, **kwargs):
        progress_calls["count"] += 1
        return "ignored"

    monkeypatch.setattr(client, "_post_progress_update", fake_post_progress_update)

    payload = {
        "project_id": "proj1",
        "input_audio_b64": base64.b64encode(b"fake-wav-audio" * 8).decode("utf-8"),
        "input_audio_filename": "lecture.wav",
        "output_name": "enhanced-audio",
        "output_format": "mp3",
        "enhancement_model": "deepfilternet",
    }

    with pytest.raises(JobCancelledError):
        client._process_enhance_job("job_test", payload)

    assert progress_calls["count"] >= 1
    assert cancel_calls == ["job_test"]


def test_worker_client_applies_speech_cleanup_locally_when_available(monkeypatch, tmp_path: Path):
    client = WorkerClient(
        server_url="http://example.invalid",
        config_path=tmp_path / "worker.json",
        worker_name="test-worker",
        invite_token=None,
        poll_seconds=1,
    )

    input_bytes = b"fake-wav-audio" * 8
    output_bytes = b"fake-mp3-output" * 8

    class FakeEnhanceService:
        def enhance(self, **kwargs):
            output_path = kwargs["output_base_path"].with_suffix(".mp3")
            output_path.write_bytes(output_bytes)
            kwargs["on_stage"]("enhance", 0.5, "Improving audio", 12)
            return output_path

        def cancel(self, job_id: str) -> None:
            raise AssertionError(f"cancel should not be called for {job_id}")

    cleanup_calls: list[dict[str, object]] = []

    class FakeSpeechCleanupService:
        def capability_status(self):
            return True, "ready"

        def cleanup_audio_file(self, **kwargs):
            cleanup_calls.append(kwargs)
            kwargs["on_stage"](0.5, "Cleaning speech", 9)
            return SpeechCleanupResult(applied=True, removed_pause_count=1, removed_filler_count=1, duration_seconds=2.2)

    progress_updates: list[tuple[float, str | None, str | None, int | None]] = []

    def fake_post_progress_update(job_id, *, progress, stage=None, detail=None, eta_seconds=None):
        progress_updates.append((progress, stage, detail, eta_seconds))
        return "running"

    monkeypatch.setattr("radcast.worker_client.probe_duration_seconds", lambda _path: 4.0)
    client.enhance_service = FakeEnhanceService()
    client.speech_cleanup_service = FakeSpeechCleanupService()
    monkeypatch.setattr(client, "_post_progress_update", fake_post_progress_update)

    payload = {
        "project_id": "proj1",
        "input_audio_b64": base64.b64encode(input_bytes).decode("utf-8"),
        "input_audio_filename": "lecture.wav",
        "output_name": "enhanced-audio",
        "output_format": "mp3",
        "enhancement_model": "deepfilternet",
        "max_silence_seconds": 1.0,
        "remove_filler_words": True,
        "filler_removal_mode": "normal",
    }

    result = client._process_enhance_job("job_test", payload)

    assert result["cleanup_applied"] is True
    assert result["cleanup_summary"] == "Shortened 1 long pause, removed 1 filler word."
    assert result["duration_seconds"] == 4.0
    assert cleanup_calls
    assert cleanup_calls[0]["filler_removal_mode"] == FillerRemovalMode.NORMAL
    assert any(stage == "cleanup" and detail and "local helper device" in detail.lower() for _, stage, detail, _ in progress_updates)
