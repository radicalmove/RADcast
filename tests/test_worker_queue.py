from __future__ import annotations

import base64
import shutil
import time
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from radcast.api import app
from radcast.services.speech_cleanup import SpeechCleanupResult


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
                "stage_durations_seconds": {"total": 7.1},
            },
        )
        assert complete.status_code == 200
        assert complete.json()["status"] == "accepted"
        assert captured == {
            "max_silence_seconds": 0.5,
            "remove_filler_words": True,
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
