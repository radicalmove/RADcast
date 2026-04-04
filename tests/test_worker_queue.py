from __future__ import annotations

import base64
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from radcast.api import app
from radcast.exceptions import JobCancelledError
from radcast.models import CaptionFormat, FillerRemovalMode
from radcast.services.speech_cleanup import SpeechCleanupResult
from radcast.worker_client import (
    WorkerClient,
    _apply_local_caption_defaults,
    _heartbeat_eta_seconds,
    _heartbeat_progress,
)


_LOCAL_CAPTION_ENV_KEYS = (
    "RADCAST_RUNTIME_CONTEXT",
    "RADCAST_CAPTION_BACKEND",
    "RADCAST_CAPTION_ACCURATE_MODEL",
    "RADCAST_CAPTION_ACCURATE_BEAM_SIZE",
    "RADCAST_CAPTION_REVIEWED_MODEL",
    "RADCAST_CAPTION_REVIEWED_BEAM_SIZE",
)


@pytest.fixture(autouse=True)
def _restore_local_caption_env():
    original_values = {key: os.environ.get(key) for key in _LOCAL_CAPTION_ENV_KEYS}
    try:
        yield
    finally:
        for key, value in original_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_worker_queue_round_trip_completes_job(monkeypatch):
    client = TestClient(app)
    project_id = f"radcast-worker-{uuid.uuid4().hex[:8]}"
    sample_b64 = base64.b64encode(b"fake-wav-audio" * 8).decode("utf-8")
    from radcast import api as api_module

    monkeypatch.setattr(api_module.worker_manager, "list_workers", lambda: [])
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


def test_worker_progress_preserves_helper_cleanup_stage(monkeypatch):
    client = TestClient(app)
    project_id = f"radcast-worker-{uuid.uuid4().hex[:8]}"
    sample_b64 = base64.b64encode(b"fake-wav-audio" * 8).decode("utf-8")
    from radcast import api as api_module

    monkeypatch.setattr(api_module.worker_manager, "list_workers", lambda: [])
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
                "enhancement_model": "none",
                "max_silence_seconds": 1.0,
                "remove_filler_words": True,
            },
        )
        assert queued.status_code == 200
        job_id = queued.json()["job_id"]

        pull = client.post("/workers/pull", json={"worker_id": worker_id, "api_key": api_key})
        assert pull.status_code == 200

        progress = client.post(
            f"/workers/jobs/{job_id}/progress",
            json={
                "worker_id": worker_id,
                "api_key": api_key,
                "progress": 0.72,
                "stage": "cleanup",
                "detail": "Transcribing speech timing for cleanup. On your local helper device.",
                "eta_seconds": 244,
            },
        )
        assert progress.status_code == 200
        assert progress.json()["status"] == "running"

        running = client.get(f"/jobs/{job_id}", params={"project_id": project_id})
        assert running.status_code == 200
        running_payload = running.json()
        assert running_payload["status"] == "running"
        assert running_payload["stage"] == "cleanup"
        assert running_payload["eta_seconds"] == 244
    finally:
        api_module.enhance_service.is_model_available = original_is_model_available
        for path in Path("projects").glob(f"*__{project_id}"):
            if path.exists():
                shutil.rmtree(path)
        project_root = Path("projects") / project_id
        if project_root.exists():
            shutil.rmtree(project_root)


def test_heartbeat_eta_counts_down():
    assert _heartbeat_eta_seconds(120, 10.0, now_monotonic=40.0) == 90
    assert _heartbeat_eta_seconds(10, 10.0, now_monotonic=40.0) == 0
    assert _heartbeat_eta_seconds(None, 10.0, now_monotonic=40.0) is None


def test_heartbeat_progress_creeps_windowed_caption_stage():
    base_progress = 0.2549

    progressed = _heartbeat_progress(
        base_progress,
        stage="captions",
        detail="Transcribing speech for captions. Window 1 of 27.",
        progress_updated_at_monotonic=10.0,
        cleanup_requested=False,
        caption_requested=True,
        enhancement_requested=False,
        remaining_eta_seconds=700,
        now_monotonic=130.0,
    )

    assert progressed > base_progress
    assert progressed < 0.985


def test_heartbeat_progress_does_not_creep_without_window_detail():
    base_progress = 0.2549

    progressed = _heartbeat_progress(
        base_progress,
        stage="captions",
        detail="Transcribing speech for captions.",
        progress_updated_at_monotonic=10.0,
        cleanup_requested=False,
        caption_requested=True,
        enhancement_requested=False,
        remaining_eta_seconds=700,
        now_monotonic=130.0,
    )

    assert progressed == base_progress


def test_heartbeat_progress_creeps_windowed_caption_stage_without_eta():
    base_progress = 0.2549

    progressed = _heartbeat_progress(
        base_progress,
        stage="captions",
        detail="Transcribing speech for captions. Window 1 of 27.",
        progress_updated_at_monotonic=10.0,
        cleanup_requested=False,
        caption_requested=True,
        enhancement_requested=False,
        remaining_eta_seconds=None,
        now_monotonic=130.0,
    )

    assert progressed > base_progress


def test_heartbeat_progress_creeps_reviewed_caption_stage_without_eta():
    base_progress = 0.82

    progressed = _heartbeat_progress(
        base_progress,
        stage="captions",
        detail="Reviewing low-confidence caption lines with whisper.cpp (medium). 1 of 18. On your local helper device.",
        progress_updated_at_monotonic=10.0,
        cleanup_requested=False,
        caption_requested=True,
        enhancement_requested=False,
        remaining_eta_seconds=None,
        now_monotonic=130.0,
    )

    assert progressed > base_progress
    assert progressed < 0.985


def test_apply_local_caption_defaults_on_macos(monkeypatch):
    for key in (
        "RADCAST_RUNTIME_CONTEXT",
        "RADCAST_CAPTION_BACKEND",
        "RADCAST_CAPTION_ACCURATE_MODEL",
        "RADCAST_CAPTION_ACCURATE_BEAM_SIZE",
        "RADCAST_CAPTION_REVIEWED_MODEL",
        "RADCAST_CAPTION_REVIEWED_BEAM_SIZE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("radcast.worker_client.platform.system", lambda: "Darwin")

    _apply_local_caption_defaults()

    assert os.environ["RADCAST_RUNTIME_CONTEXT"] == "local_helper"
    assert os.environ["RADCAST_CAPTION_BACKEND"] == "auto"
    assert os.environ["RADCAST_CAPTION_ACCURATE_MODEL"] == "small"
    assert os.environ["RADCAST_CAPTION_ACCURATE_BEAM_SIZE"] == "3"
    assert os.environ["RADCAST_CAPTION_REVIEWED_MODEL"] == "medium"
    assert os.environ["RADCAST_CAPTION_REVIEWED_BEAM_SIZE"] == "3"


def test_apply_local_caption_defaults_does_not_override_explicit_env(monkeypatch):
    monkeypatch.setenv("RADCAST_CAPTION_ACCURATE_MODEL", "medium")
    monkeypatch.setenv("RADCAST_CAPTION_REVIEWED_MODEL", "large-v3")
    monkeypatch.setattr("radcast.worker_client.platform.system", lambda: "Darwin")

    _apply_local_caption_defaults()

    assert os.environ["RADCAST_CAPTION_ACCURATE_MODEL"] == "medium"
    assert os.environ["RADCAST_CAPTION_REVIEWED_MODEL"] == "large-v3"


def test_worker_completion_applies_server_side_speech_cleanup(monkeypatch):
    client = TestClient(app)
    project_id = f"radcast-worker-{uuid.uuid4().hex[:8]}"
    sample_b64 = base64.b64encode(b"fake-wav-audio" * 8).decode("utf-8")
    from radcast import api as api_module

    monkeypatch.setattr(api_module.worker_manager, "list_workers", lambda: [])
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


def test_worker_completion_generates_server_side_captions(monkeypatch):
    client = TestClient(app)
    project_id = f"radcast-worker-{uuid.uuid4().hex[:8]}"
    sample_b64 = base64.b64encode(b"fake-wav-audio" * 8).decode("utf-8")
    from radcast import api as api_module

    monkeypatch.setattr(api_module.worker_manager, "list_workers", lambda: [])
    original_is_model_available = api_module.enhance_service.is_model_available

    def fake_generate_caption_file(*, audio_path: Path, caption_format: CaptionFormat, **kwargs):
        caption_path = audio_path.with_suffix(f".{caption_format.value}")
        caption_path.write_text("WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\nHello world\n", encoding="utf-8")
        return SimpleNamespace(caption_path=caption_path, caption_format=caption_format, segment_count=1)

    monkeypatch.setattr("radcast.worker_manager.speech_cleanup_service.generate_caption_file", fake_generate_caption_file)
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
                "caption_format": "vtt",
                "enhancement_model": "deepfilternet",
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

        for _ in range(20):
            payload = client.get(f"/jobs/{job_id}", params={"project_id": project_id}).json()
            if payload["status"] == "completed":
                break
            time.sleep(0.05)
        else:
            raise AssertionError("worker caption finalization did not complete in time")

        assert payload["outputs"]["audio_path"].endswith(".mp3")
        assert payload["outputs"]["caption_path"].endswith(".vtt")
        assert payload["logs"][-1].endswith("generated VTT captions.")
    finally:
        api_module.enhance_service.is_model_available = original_is_model_available
        for path in Path("projects").glob(f"*__{project_id}"):
            if path.exists():
                shutil.rmtree(path)
        project_root = Path("projects") / project_id
        if project_root.exists():
            shutil.rmtree(project_root)


def test_worker_completion_skips_server_caption_generation_when_helper_already_generated_it(monkeypatch):
    client = TestClient(app)
    project_id = f"radcast-worker-{uuid.uuid4().hex[:8]}"
    sample_b64 = base64.b64encode(b"fake-wav-audio" * 8).decode("utf-8")
    from radcast import api as api_module

    monkeypatch.setattr(api_module.worker_manager, "list_workers", lambda: [])
    original_is_model_available = api_module.enhance_service.is_model_available

    def fail_generate_caption_file(**kwargs):
        raise AssertionError("server-side caption generation should not run when helper already generated captions")

    monkeypatch.setattr("radcast.worker_manager.speech_cleanup_service.generate_caption_file", fail_generate_caption_file)
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
                "caption_format": "vtt",
                "enhancement_model": "none",
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
                "caption_b64": base64.b64encode(b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n").decode("utf-8"),
                "output_format": "mp3",
                "duration_seconds": 3.4,
                "stage_durations_seconds": {"total": 7.1, "captions": 2.0},
            },
        )
        assert complete.status_code == 200
        assert complete.json()["status"] == "completed"

        payload = client.get(f"/jobs/{job_id}", params={"project_id": project_id}).json()
        assert payload["status"] == "completed"
        assert payload["outputs"]["caption_path"].endswith(".vtt")
        assert payload["logs"][-1].endswith("generated VTT captions.")
    finally:
        api_module.enhance_service.is_model_available = original_is_model_available
        for path in Path("projects").glob(f"*__{project_id}"):
            if path.exists():
                shutil.rmtree(path)
        project_root = Path("projects") / project_id
        if project_root.exists():
            shutil.rmtree(project_root)


def test_worker_progress_is_ignored_after_server_caption_finalization_starts(monkeypatch):
    client = TestClient(app)
    project_id = f"radcast-worker-{uuid.uuid4().hex[:8]}"
    sample_b64 = base64.b64encode(b"fake-wav-audio" * 8).decode("utf-8")
    from radcast import api as api_module

    monkeypatch.setattr(api_module.worker_manager, "list_workers", lambda: [])
    original_is_model_available = api_module.enhance_service.is_model_available

    started = threading.Event()
    release = threading.Event()

    def fake_generate_caption_file(*, audio_path: Path, caption_format: CaptionFormat, **kwargs):
        started.set()
        assert release.wait(timeout=1.0)
        caption_path = audio_path.with_suffix(f".{caption_format.value}")
        caption_path.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello world\n", encoding="utf-8")
        return SimpleNamespace(caption_path=caption_path, caption_format=caption_format, segment_count=1)

    monkeypatch.setattr("radcast.worker_manager.speech_cleanup_service.generate_caption_file", fake_generate_caption_file)
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
                "caption_format": "vtt",
                "enhancement_model": "deepfilternet",
                "max_silence_seconds": 1.0,
                "remove_filler_words": True,
                "filler_removal_mode": "aggressive",
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
                "duration_seconds": 5.2,
                "cleanup_applied": True,
                "cleanup_summary": "Shortened 1 long pause, removed 1 filler word.",
                "stage_durations_seconds": {"total": 7.1, "cleanup": 1.2},
            },
        )
        assert complete.status_code == 200
        assert complete.json()["status"] == "accepted"
        assert started.wait(timeout=2.5)

        in_progress = client.get(f"/jobs/{job_id}", params={"project_id": project_id}).json()
        assert in_progress["stage"] == "captions"
        assert in_progress["progress"] == pytest.approx(0.72)

        stale_progress = client.post(
            f"/workers/jobs/{job_id}/progress",
            json={
                "worker_id": worker_id,
                "api_key": api_key,
                "progress": 0.96,
                "stage": "cleanup",
                "detail": "Transcribing speech timing for cleanup.",
                "eta_seconds": 5539,
            },
        )
        assert stale_progress.status_code == 200
        assert stale_progress.json()["status"] == "ignored"

        after_stale_update = client.get(f"/jobs/{job_id}", params={"project_id": project_id}).json()
        assert after_stale_update["stage"] == "captions"
        assert after_stale_update["progress"] == pytest.approx(0.72)

        release.set()
        for _ in range(20):
            payload = client.get(f"/jobs/{job_id}", params={"project_id": project_id}).json()
            if payload["status"] == "completed":
                break
            time.sleep(0.05)
        else:
            raise AssertionError("worker caption finalization did not complete in time")
    finally:
        release.set()
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

    monkeypatch.setattr(api_module.worker_manager, "list_workers", lambda: [])
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


def test_cancel_endpoint_marks_running_worker_job_cancelled(monkeypatch):
    client = TestClient(app)
    project_id = f"radcast-worker-{uuid.uuid4().hex[:8]}"
    sample_b64 = base64.b64encode(b"fake-wav-audio" * 8).decode("utf-8")
    from radcast import api as api_module

    monkeypatch.setattr(api_module.worker_manager, "list_workers", lambda: [])
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


def test_worker_client_forwards_trim_values_into_enhancement(monkeypatch, tmp_path: Path):
    client = WorkerClient(
        server_url="http://example.invalid",
        config_path=tmp_path / "worker.json",
        worker_name="test-worker",
        invite_token=None,
        poll_seconds=1,
    )

    captured: dict[str, object] = {}

    class FakeEnhanceService:
        def enhance(self, **kwargs):
            captured.update(kwargs)
            output_path = kwargs["output_base_path"].with_suffix(".mp3")
            output_path.write_bytes(b"fake-mp3-output" * 4)
            return output_path

        def cancel(self, job_id: str) -> None:
            raise AssertionError(f"cancel should not be called for {job_id}")

    class FakeSpeechCleanupService:
        def capability_status(self):
            return False, "not available"

    monkeypatch.setattr("radcast.worker_client.probe_duration_seconds", lambda _path: 4.0)
    monkeypatch.setattr(client, "_post_progress_update", lambda *args, **kwargs: "running")
    client.enhance_service = FakeEnhanceService()
    client.speech_cleanup_service = FakeSpeechCleanupService()

    payload = {
        "project_id": "proj1",
        "input_audio_b64": base64.b64encode(b"fake-wav-audio" * 8).decode("utf-8"),
        "input_audio_filename": "lecture.wav",
        "output_name": "enhanced-audio",
        "output_format": "mp3",
        "enhancement_model": "none",
        "clip_start_seconds": 1.25,
        "clip_end_seconds": 3.75,
    }

    client._process_enhance_job("job_test", payload)

    assert captured["clip_start_seconds"] == 1.25
    assert captured["clip_end_seconds"] == 3.75


def test_worker_client_postprocesses_trimmed_output_duration(monkeypatch, tmp_path: Path):
    client = WorkerClient(
        server_url="http://example.invalid",
        config_path=tmp_path / "worker.json",
        worker_name="test-worker",
        invite_token=None,
        poll_seconds=1,
    )

    output_path_holder: dict[str, Path] = {}
    cleanup_calls: list[dict[str, object]] = []
    caption_calls: list[dict[str, object]] = []
    captured_trim: dict[str, float | None] = {}

    class FakeEnhanceService:
        def enhance(self, **kwargs):
            captured_trim["clip_start_seconds"] = kwargs.get("clip_start_seconds")
            captured_trim["clip_end_seconds"] = kwargs.get("clip_end_seconds")
            output_path = kwargs["output_base_path"].with_suffix(".mp3")
            output_path.write_bytes(b"fake-mp3-output" * 8)
            output_path_holder["path"] = output_path
            return output_path

        def cancel(self, job_id: str) -> None:
            raise AssertionError(f"cancel should not be called for {job_id}")

    class FakeSpeechCleanupService:
        def capability_status(self):
            return True, "ready"

        def cleanup_audio_file(self, **kwargs):
            cleanup_calls.append(kwargs)
            return SpeechCleanupResult(applied=True, removed_pause_count=1, removed_filler_count=0, duration_seconds=2.4)

        def generate_caption_file(self, **kwargs):
            caption_calls.append(kwargs)
            caption_path = Path(kwargs["audio_path"]).with_suffix(".vtt")
            caption_path.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n", encoding="utf-8")
            return SimpleNamespace(caption_path=caption_path, caption_format=CaptionFormat.VTT, segment_count=1)

        def estimate_caption_runtime_seconds(self, _duration_seconds, *, quality_mode=None):
            return 14

    def fake_probe_duration(path: Path) -> float:
        resolved = Path(path)
        if resolved == output_path_holder.get("path"):
            return 2.4
        return 6.0

    monkeypatch.setattr("radcast.worker_client.probe_duration_seconds", fake_probe_duration)
    monkeypatch.setattr(client, "_post_progress_update", lambda *args, **kwargs: "running")
    client.enhance_service = FakeEnhanceService()
    client.speech_cleanup_service = FakeSpeechCleanupService()

    payload = {
        "project_id": "proj1",
        "input_audio_b64": base64.b64encode(b"fake-wav-audio" * 8).decode("utf-8"),
        "input_audio_filename": "lecture.wav",
        "output_name": "enhanced-audio",
        "output_format": "mp3",
        "enhancement_model": "none",
        "clip_start_seconds": 1.1,
        "clip_end_seconds": 3.5,
        "max_silence_seconds": 1.0,
        "caption_format": "vtt",
    }

    result = client._process_enhance_job("job_test", payload)

    assert captured_trim == {
        "clip_start_seconds": 1.1,
        "clip_end_seconds": 3.5,
    }
    assert cleanup_calls
    assert cleanup_calls[0]["audio_path"] == output_path_holder["path"]
    assert caption_calls
    assert caption_calls[0]["audio_path"] == output_path_holder["path"]
    assert result["duration_seconds"] == 2.4
    assert result["caption_b64"]


def test_worker_client_reserves_caption_band_after_local_cleanup(monkeypatch, tmp_path: Path):
    client = WorkerClient(
        server_url="http://example.invalid",
        config_path=tmp_path / "worker.json",
        worker_name="test-worker",
        invite_token=None,
        poll_seconds=1,
    )

    output_bytes = b"fake-mp3-output" * 8

    class FakeEnhanceService:
        def enhance(self, **kwargs):
            output_path = kwargs["output_base_path"].with_suffix(".mp3")
            output_path.write_bytes(output_bytes)
            kwargs["on_stage"]("enhance", 0.5, "Improving audio", 12)
            return output_path

        def cancel(self, job_id: str) -> None:
            raise AssertionError(f"cancel should not be called for {job_id}")

    class FakeSpeechCleanupService:
        def capability_status(self):
            return True, "ready"

        def cleanup_audio_file(self, **kwargs):
            kwargs["on_stage"](0.98, "Saving cleaned audio.", 5)
            return SpeechCleanupResult(applied=True, removed_pause_count=1, removed_filler_count=1, duration_seconds=2.2)

        def generate_caption_file(self, **kwargs):
            kwargs["on_stage"](0.55, "Transcribing speech for captions.", 14)
            caption_path = Path(kwargs["audio_path"]).with_suffix(".vtt")
            caption_path.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n", encoding="utf-8")
            return SimpleNamespace(caption_path=caption_path, caption_format=CaptionFormat.VTT, segment_count=1)

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
        "input_audio_b64": base64.b64encode(b"fake-wav-audio" * 8).decode("utf-8"),
        "input_audio_filename": "lecture.wav",
        "output_name": "enhanced-audio",
        "output_format": "mp3",
        "enhancement_model": "none",
        "max_silence_seconds": 1.0,
        "remove_filler_words": True,
        "filler_removal_mode": "aggressive",
        "caption_format": "vtt",
    }

    client._process_enhance_job("job_test", payload)

    cleanup_progresses = [progress for progress, stage, _detail, _eta in progress_updates if stage == "cleanup"]
    assert cleanup_progresses
    assert max(cleanup_progresses) < 0.87


def test_worker_client_generates_captions_locally_when_available(monkeypatch, tmp_path: Path):
    client = WorkerClient(
        server_url="http://example.invalid",
        config_path=tmp_path / "worker.json",
        worker_name="test-worker",
        invite_token=None,
        poll_seconds=1,
    )

    output_bytes = b"fake-mp3-output" * 8

    class FakeEnhanceService:
        def enhance(self, **kwargs):
            output_path = kwargs["output_base_path"].with_suffix(".mp3")
            output_path.write_bytes(output_bytes)
            kwargs["on_stage"]("enhance", 0.5, "Improving audio", 12)
            return output_path

        def cancel(self, job_id: str) -> None:
            raise AssertionError(f"cancel should not be called for {job_id}")

    caption_calls: list[dict[str, object]] = []

    class FakeSpeechCleanupService:
        def capability_status(self):
            return True, "ready"

        def generate_caption_file(self, **kwargs):
            caption_calls.append(kwargs)
            kwargs["on_stage"](0.55, "Transcribing speech for captions.", 14)
            caption_path = Path(kwargs["audio_path"]).with_suffix(".vtt")
            caption_path.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n", encoding="utf-8")
            return SimpleNamespace(caption_path=caption_path, caption_format=CaptionFormat.VTT, segment_count=1)

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
        "input_audio_b64": base64.b64encode(b"fake-wav-audio" * 8).decode("utf-8"),
        "input_audio_filename": "lecture.wav",
        "output_name": "enhanced-audio",
        "output_format": "mp3",
        "enhancement_model": "none",
        "caption_format": "vtt",
    }

    result = client._process_enhance_job("job_test", payload)

    assert caption_calls
    assert result["caption_b64"]
    assert any(stage == "captions" and detail and "local helper device" in detail.lower() for _, stage, detail, _ in progress_updates)
