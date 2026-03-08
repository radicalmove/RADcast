from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from radcast.api import app


def test_ui_homepage_renders():
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "RADcast Studio" in response.text
    assert "Create project" in response.text


def test_project_create_and_list_roundtrip():
    client = TestClient(app)
    project_id = f"radcast-{uuid.uuid4().hex[:8]}"
    project_root = Path("projects") / project_id

    try:
        created = client.post(
            "/projects",
            json={"project_id": project_id, "course": "CRJU150", "module": "M9", "lesson": "L1"},
        )
        assert created.status_code == 200
        payload = created.json()
        assert payload["project_id"] == project_id
        assert payload["project_ref"]

        listed = client.get("/projects")
        assert listed.status_code == 200
        projects = listed.json()["projects"]
        ids = [item["project_id"] for item in projects]
        assert project_id in ids
    finally:
        # Also clean up scoped variant if project scoping is on.
        for path in Path("projects").glob(f"*__{project_id}"):
            if path.exists():
                shutil.rmtree(path)
        if project_root.exists():
            shutil.rmtree(project_root)


def test_source_audio_upload_list_and_enhance_by_hash(monkeypatch):
    client = TestClient(app)
    project_id = f"radcast-{uuid.uuid4().hex[:8]}"
    sample_b64 = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVoxMjM0NTY3ODkw"

    def fake_enhance(*, output_base_path, on_stage, **kwargs):
        on_stage("enhance", 0.65, "Improving audio", 12)
        final_path = output_base_path.with_suffix(".mp3")
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_bytes(b"fake-mp3")
        return final_path

    monkeypatch.setattr("radcast.api.probe_duration_seconds", lambda path: 4.2)
    monkeypatch.setattr("radcast.api.enhance_service.enhance", fake_enhance)

    try:
        created = client.post("/projects", json={"project_id": project_id})
        assert created.status_code == 200

        uploaded = client.post(
            f"/projects/{project_id}/source-audio",
            json={"filename": "lecture.wav", "audio_b64": sample_b64},
        )
        assert uploaded.status_code == 200
        uploaded_payload = uploaded.json()
        assert uploaded_payload["audio_hash"]
        assert uploaded_payload["duration_seconds"] == 4.2

        listed = client.get(f"/projects/{project_id}/source-audio")
        assert listed.status_code == 200
        samples = listed.json()["samples"]
        assert len(samples) == 1
        assert samples[0]["audio_hash"] == uploaded_payload["audio_hash"]
        assert samples[0]["source_filename"] == "lecture.wav"
        assert samples[0]["duration_seconds"] == 4.2

        started = client.post(
            "/enhance/simple",
            json={
                "project_id": project_id,
                "input_audio_hash": uploaded_payload["audio_hash"],
                "output_format": "mp3",
            },
        )
        assert started.status_code == 200
        job_id = started.json()["job_id"]

        final_payload = None
        for _ in range(30):
            polled = client.get(f"/jobs/{job_id}", params={"project_id": project_id})
            assert polled.status_code == 200
            final_payload = polled.json()
            if final_payload["status"] == "completed":
                break

        assert final_payload is not None
        assert final_payload["status"] == "completed"
        assert final_payload["outputs"]["audio_play_url"]
    finally:
        for path in Path("projects").glob(f"*__{project_id}"):
            if path.exists():
                shutil.rmtree(path)
        project_root = Path("projects") / project_id
        if project_root.exists():
            shutil.rmtree(project_root)
