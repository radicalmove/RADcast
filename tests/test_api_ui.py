from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer

import radcast.api as radcast_api
from radcast.manifests import ManifestStore
from radcast.models import CaptionFormat, EnhancementModel, OutputFormat, OutputMetadata

app = radcast_api.app


def _bridge_user(client: TestClient, *, sub: int, email: str, display_name: str) -> None:
    serializer = URLSafeTimedSerializer("radcast-dev-session-secret", salt="app-bridge-radcast-v1")
    token = serializer.dumps(
        {
            "sub": sub,
            "email": email,
            "display_name": display_name,
            "is_admin": False,
            "issuer": "psychek",
        }
    )
    response = client.get(f"/auth/bridge?token={token}", follow_redirects=False)
    assert response.status_code == 302


def test_ui_homepage_renders():
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "RADcast Studio" in response.text
    assert "Create project" in response.text
    assert "Recent projects" in response.text
    assert "Don't enhance audio" in response.text
    assert "Reduce silence longer than" in response.text
    assert "Remove umms and ahhs" in response.text
    assert "Closed captions" in response.text


def test_worker_invite_and_status_endpoints_render(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(radcast_api.worker_manager, "list_workers", lambda: [])
    invite = client.post("/workers/invite", json={"capabilities": ["enhance"]})
    assert invite.status_code == 200
    payload = invite.json()
    assert "git+https://github.com/radicalmove/RADcast.git" in payload["install_command_macos"]
    assert "deepfilternet" in payload["install_command_macos"]
    assert "git-lfs" in payload["install_command_macos"]
    assert "python@3.11" in payload["install_command_macos"]
    assert "resemble-enhance" in payload["install_command_macos"]
    assert "radcast.worker_setup" in payload["install_command_macos"]
    assert payload["windows_installer_url"].startswith("http://testserver/workers/bootstrap/windows.cmd?")

    status = client.get("/workers/status")
    assert status.status_code == 200
    status_payload = status.json()
    assert "worker_total_count" in status_payload
    assert "worker_online_count" in status_payload

    models = client.get("/enhancement/models")
    assert models.status_code == 200
    models_payload = models.json()
    assert models_payload["default_model"] in {"resemble", "deepfilternet", "studio", "studio_v18"}
    assert any(item["id"] == "none" for item in models_payload["models"])
    assert any(item["id"] == "resemble" for item in models_payload["models"])
    assert any(item["id"] == "deepfilternet" for item in models_payload["models"])
    assert any(item["id"] == "studio" for item in models_payload["models"])
    assert any(item["id"] == "studio_v18" for item in models_payload["models"])
    assert "speech_cleanup" in models_payload


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


def test_projects_endpoint_returns_recent_activity_first():
    client = TestClient(app)
    older_project_id = f"radcast-old-{uuid.uuid4().hex[:8]}"
    newer_project_id = f"radcast-new-{uuid.uuid4().hex[:8]}"
    created_roots: list[Path] = []

    try:
        older_created = client.post("/projects", json={"project_id": older_project_id})
        newer_created = client.post("/projects", json={"project_id": newer_project_id})
        assert older_created.status_code == 200
        assert newer_created.status_code == 200

        older_root = Path(older_created.json()["project_root"])
        newer_root = Path(newer_created.json()["project_root"])
        created_roots.extend([older_root, newer_root])

        older_ts = 1_700_000_000
        newer_ts = 1_800_000_000
        for path in older_root.joinpath("manifests").glob("*.json"):
            os.utime(path, (older_ts, older_ts))
        os.utime(older_root, (older_ts, older_ts))

        for path in newer_root.joinpath("manifests").glob("*.json"):
            os.utime(path, (newer_ts, newer_ts))
        os.utime(newer_root, (newer_ts, newer_ts))

        listed = client.get("/projects")
        assert listed.status_code == 200
        rows = listed.json()["projects"]
        older_index = next(idx for idx, row in enumerate(rows) if row["project_id"] == older_project_id)
        newer_index = next(idx for idx, row in enumerate(rows) if row["project_id"] == newer_project_id)
        assert newer_index < older_index
        assert rows[newer_index]["updated_at"]
    finally:
        for root in created_roots:
            if root.exists():
                shutil.rmtree(root)


def test_source_audio_upload_list_and_enhance_by_hash(monkeypatch):
    client = TestClient(app)
    project_id = f"radcast-{uuid.uuid4().hex[:8]}"
    sample_b64 = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVoxMjM0NTY3ODkw"
    monkeypatch.setattr(radcast_api.worker_manager, "list_workers", lambda: [])

    def fake_enhance(*, output_base_path, on_stage, **kwargs):
        on_stage("enhance", 0.65, "Improving audio", 12)
        final_path = output_base_path.with_suffix(".mp3")
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_bytes(b"fake-mp3")
        return final_path

    monkeypatch.setattr("radcast.api.probe_duration_seconds", lambda path: 4.2)
    monkeypatch.setattr("radcast.api.enhance_service.enhance", fake_enhance)
    monkeypatch.setattr("radcast.api.enhance_service.is_model_available", lambda _model: True)

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
                "enhancement_model": "resemble",
            },
        )
        assert started.status_code == 200
        job_id = started.json()["job_id"]

        final_payload = client.get(f"/jobs/{job_id}", params={"project_id": project_id}).json()
        assert final_payload["status"] in {"queued", "running"}
        assert final_payload["stage"] in {"queued_remote", "worker_running"}
    finally:
        for path in Path("projects").glob(f"*__{project_id}"):
            if path.exists():
                shutil.rmtree(path)
        project_root = Path("projects") / project_id
        if project_root.exists():
            shutil.rmtree(project_root)


def test_source_audio_delete_removes_saved_file(monkeypatch):
    client = TestClient(app)
    project_id = f"radcast-{uuid.uuid4().hex[:8]}"
    sample_b64 = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVoxMjM0NTY3ODkw"

    monkeypatch.setattr("radcast.api.probe_duration_seconds", lambda path: 4.2)

    try:
        created = client.post("/projects", json={"project_id": project_id})
        assert created.status_code == 200

        uploaded = client.post(
            f"/projects/{project_id}/source-audio",
            json={"filename": "lecture.wav", "audio_b64": sample_b64},
        )
        assert uploaded.status_code == 200
        uploaded_payload = uploaded.json()

        saved_path = Path(uploaded_payload["saved_path"])
        assert saved_path.exists()

        deleted = client.post(
            f"/projects/{project_id}/source-audio/delete",
            json={"audio_hash": uploaded_payload["audio_hash"]},
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
        assert deleted.json()["removed_file"] is True
        assert not saved_path.exists()

        listed = client.get(f"/projects/{project_id}/source-audio")
        assert listed.status_code == 200
        assert listed.json()["samples"] == []
    finally:
        for path in Path("projects").glob(f"*__{project_id}"):
            if path.exists():
                shutil.rmtree(path)
        project_root = Path("projects") / project_id
        if project_root.exists():
            shutil.rmtree(project_root)


def test_project_settings_roundtrip_persists_last_used_options():
    client = TestClient(app)
    project_id = f"radcast-{uuid.uuid4().hex[:8]}"
    project_root: Path | None = None
    sample_b64 = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVoxMjM0NTY3ODkw"

    try:
        created = client.post("/projects", json={"project_id": project_id})
        assert created.status_code == 200
        project_root = Path(created.json()["project_root"])

        default_settings = client.get(f"/projects/{project_id}/settings")
        assert default_settings.status_code == 200
        assert default_settings.json()["settings"] == {
            "selected_audio_hash": None,
            "output_format": "mp3",
            "caption_format": None,
            "caption_quality_mode": "accurate",
            "caption_glossary": None,
            "enhancement_model": "studio_v18",
            "reduce_silence_enabled": False,
            "max_silence_seconds": 1.0,
            "remove_filler_words": False,
            "filler_removal_mode": "aggressive",
        }

        uploaded = client.post(
            f"/projects/{project_id}/source-audio",
            json={"filename": "lecture.wav", "audio_b64": sample_b64},
        )
        assert uploaded.status_code == 200
        audio_hash = uploaded.json()["audio_hash"]

        updated = client.put(
            f"/projects/{project_id}/settings",
            json={
                "selected_audio_hash": audio_hash,
                "output_format": "wav",
                "caption_format": "vtt",
                "caption_quality_mode": "reviewed",
                "caption_glossary": "tikanga Māori\norganisation\nrangatiratanga",
                "enhancement_model": "none",
                "reduce_silence_enabled": True,
                "max_silence_seconds": 2.25,
                "remove_filler_words": True,
                "filler_removal_mode": "normal",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["settings"] == {
            "selected_audio_hash": audio_hash,
            "output_format": "wav",
            "caption_format": "vtt",
            "caption_quality_mode": "reviewed",
            "caption_glossary": "tikanga Māori\norganisation\nrangatiratanga",
            "enhancement_model": "none",
            "reduce_silence_enabled": True,
            "max_silence_seconds": 2.25,
            "remove_filler_words": True,
            "filler_removal_mode": "normal",
        }

        loaded = client.get(f"/projects/{project_id}/settings")
        assert loaded.status_code == 200
        assert loaded.json()["settings"] == updated.json()["settings"]

        manifest_text = (project_root / "manifests" / "project.json").read_text(encoding="utf-8")
        assert '"ui_settings"' in manifest_text
        assert audio_hash in manifest_text
    finally:
        for path in Path("projects").glob(f"*__{project_id}"):
            if path.exists():
                shutil.rmtree(path)
        if project_root and project_root.exists():
            shutil.rmtree(project_root)


def test_project_shareable_users_proxy_uses_integration_endpoint(monkeypatch):
    client = TestClient(app)
    _bridge_user(client, sub=901, email="owner@example.com", display_name="Owner")
    project_id = f"radcast-share-{uuid.uuid4().hex[:8]}"
    created_roots: list[Path] = []
    captured: dict[str, object] = {}

    class _FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers.get("Authorization")
        captured["timeout"] = timeout
        return _FakeResponse(
            {
                "success": True,
                "users": [
                    {
                        "id": 22,
                        "username": "collab",
                        "display_name": "Collaborator User",
                        "email": "collab@example.com",
                    }
                ],
            }
        )

    monkeypatch.setattr(radcast_api, "PSYCHEK_SHAREABLE_USERS_URL", "https://psychek.example/api/v1/integrations/shareable-users")
    monkeypatch.setattr(radcast_api, "PSYCHEK_INTEGRATION_API_KEY", "share-secret")
    monkeypatch.setattr(radcast_api, "urlopen", fake_urlopen)

    try:
        created = client.post("/projects", json={"project_id": project_id})
        assert created.status_code == 200
        created_roots.append(Path(created.json()["project_root"]))

        response = client.get(f"/projects/{project_id}/shareable-users")
        assert response.status_code == 200
        payload = response.json()
        assert payload["project_id"] == project_id
        assert payload["users"] == [
            {
                "id": 22,
                "username": "collab",
                "display_name": "Collaborator User",
                "email": "collab@example.com",
            }
        ]
        assert captured["authorization"] == "Bearer share-secret"
        assert "exclude_email=owner%40example.com" in str(captured["url"])
        assert captured["timeout"] == 8
    finally:
        for path in Path("projects").glob(f"*__{project_id}"):
            if path.exists():
                shutil.rmtree(path)
        for root in created_roots:
            if root.exists():
                shutil.rmtree(root)


def test_project_outputs_endpoint_includes_output_card_metadata():
    client = TestClient(app)
    project_id = f"radcast-{uuid.uuid4().hex[:8]}"
    project_root: Path | None = None

    try:
        created = client.post("/projects", json={"project_id": project_id})
        assert created.status_code == 200
        project_root = Path(created.json()["project_root"])

        manifests = project_root / "manifests"
        store = ManifestStore(manifests)
        output_path = project_root / "assets" / "enhanced_audio" / "sample.mp3"
        caption_path = project_root / "assets" / "enhanced_audio" / "sample.vtt"
        review_path = project_root / "assets" / "enhanced_audio" / "sample.vtt.review.txt"
        input_path = project_root / "assets" / "source_audio" / "sample.wav"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-mp3")
        caption_path.write_text("WEBVTT\n", encoding="utf-8")
        review_path.write_text("review me\n", encoding="utf-8")
        input_path.write_bytes(b"fake-wav")
        metadata = OutputMetadata(
            output_file=output_path,
            input_file=input_path,
            duration_seconds=4.2,
            output_format=OutputFormat.MP3,
            caption_file=caption_path,
            caption_review_file=review_path,
            caption_format=CaptionFormat.VTT,
            caption_review_required=True,
            caption_average_probability=0.63,
            caption_low_confidence_segments=3,
            caption_total_segments=12,
            enhancement_model=EnhancementModel.RESEMBLE,
            audio_tuning_label="Version 7",
            project_id=project_id,
            job_id="job_test",
        )
        store.append_output(metadata)

        outputs = client.get(f"/projects/{project_id}/outputs")
        assert outputs.status_code == 200
        payload = outputs.json()
        assert len(payload["outputs"]) == 1
        assert payload["outputs"][0]["audio_tuning_label"] == "Version 7"
        assert payload["outputs"][0]["version_number"] == 1
        assert payload["outputs"][0]["caption_format"] == "vtt"
        assert payload["outputs"][0]["caption_download_url"].endswith("sample.vtt&download=true")
        assert payload["outputs"][0]["caption_review_required"] is True
        assert payload["outputs"][0]["caption_low_confidence_segments"] == 3
        assert payload["outputs"][0]["caption_review_download_url"].endswith("sample.vtt.review.txt&download=true")
        assert payload["outputs"][0]["folder_path"].endswith("/assets/enhanced_audio")
    finally:
        for path in Path("projects").glob(f"*__{project_id}"):
            if path.exists():
                shutil.rmtree(path)
        if project_root and project_root.exists():
            shutil.rmtree(project_root)
