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
from radcast.models import (
    CaptionAccessibilityStatus,
    CaptionFormat,
    EnhancementModel,
    OutputFormat,
    OutputMetadata,
)

app = radcast_api.app
REPO_ROOT = Path(__file__).resolve().parents[1]
UI_JS_PATH = REPO_ROOT / "src" / "radcast" / "static" / "ui.js"
UI_CSS_PATH = REPO_ROOT / "src" / "radcast" / "static" / "ui.css"


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
    assert "Trim clip" in response.text
    assert "Start" in response.text
    assert "End" in response.text
    assert "Output length" in response.text
    assert "Caption quality" not in response.text


def test_ui_homepage_exposes_app_env_for_theme_overrides(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(radcast_api, "APP_ENV", "development")

    response = client.get("/")

    assert response.status_code == 200
    assert 'data-app-env="development"' in response.text


def test_ui_homepage_cache_busts_static_assets():
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert '/static/ui.css?v=' in response.text
    assert '/static/ui.js?v=' in response.text


def test_ui_homepage_renders_help_modal_shell():
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    text = response.text
    assert 'id="help-btn"' in text
    assert 'class="topbar-btn topbar-btn-help"' in text
    assert text.index('id="help-btn"') < text.index('id="switch-project-btn"')
    assert 'id="help-modal"' in text
    assert 'id="help-modal-tabs"' in text
    assert 'aria-controls="help-panel-overview"' in text
    assert 'tabindex="0"' in text
    assert 'class="help-tab-rail"' in text
    assert 'class="help-modal-body"' in text
    assert 'class="help-callout help-callout-tip"' in text
    assert 'class="help-callout help-callout-note"' in text
    assert 'class="help-callout help-callout-troubleshooting"' in text
    assert "Overview" in text
    assert "Process audio" in text
    assert "Troubleshooting" in text
    assert "RADcast helps you turn spoken-word recordings into cleaner deliverables without overwriting the source audio saved in your project." in text
    assert "Use the main process button as a status-aware control:" in text
    assert "Tip: Turn on Don't enhance audio when you only want cleanup or captions without the RADcast Optimized pass." in text
    assert "If trim controls are not visible in your current rollout, process the full file and rerun from the original project audio when trim becomes available." in text
    assert "If an upload appears to finish but no audio name shows in the workspace, choose the file again and wait for the filename or preview before processing." in text
    assert "Click <strong>Enhance audio</strong>" not in text
    assert "Placeholder guidance" not in text


def _ui_js_source() -> str:
    return UI_JS_PATH.read_text()


def _ui_css_source() -> str:
    return UI_CSS_PATH.read_text()


def test_help_modal_redesign_styles_exist():
    css = _ui_css_source()

    assert ".topbar-btn.topbar-btn-help" in css
    assert ".help-tab-rail" in css
    assert ".help-modal-body" in css
    assert ".help-callout" in css
    assert ".help-callout-tip" in css
    assert ".help-callout-troubleshooting" in css


def test_help_modal_binding_happens_before_project_loading():
    lines = _ui_js_source().splitlines()
    bind_line = next(index for index, line in enumerate(lines, start=1) if line.strip() == "bindHelpModal();")
    load_line = next(index for index, line in enumerate(lines, start=1) if line.strip() == "await loadProjects();")

    assert bind_line < load_line


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
    assert "torch==2.1.1" in payload["install_command_macos"]
    assert "resemble-enhance" in payload["install_command_macos"]
    assert "radcast.worker_setup" in payload["install_command_macos"]
    assert payload["install_command_macos"].index("resemble-enhance") < payload["install_command_macos"].index("torch==2.1.1")
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


def test_worker_timeout_failure_switches_to_server_fallback(monkeypatch):
    client = TestClient(app)

    called: dict[str, object] = {}

    def fake_fallback(job_id: str, *, reason: str, allowed_statuses: set[str] | None = None) -> bool:
        called["job_id"] = job_id
        called["reason"] = reason
        called["allowed_statuses"] = allowed_statuses
        return True

    monkeypatch.setattr(radcast_api, "_run_claimed_fallback_job", fake_fallback)
    monkeypatch.setattr(radcast_api, "WORKER_FALLBACK_ENABLED", True)

    def unexpected_fail(job_id, req):
        raise AssertionError("worker_manager.fail_job should not be called for helper timeout fallback")

    monkeypatch.setattr(radcast_api.worker_manager, "fail_job", unexpected_fail)

    response = client.post(
        "/workers/jobs/job_timeout/fail",
        json={
            "worker_id": "wrk_test",
            "api_key": "secret",
            "error": "RADcast Optimized timed out after 1816s on the helper device.",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "fallback_local"}
    assert called["job_id"] == "job_timeout"
    assert called["allowed_statuses"] == {"running"}
    assert "Switching to RADcast server fallback." in str(called["reason"])


def test_caption_only_worker_job_skips_fallback_watch_when_superseding_running_helper_job(monkeypatch):
    client = TestClient(app)
    project_id = f"radcast-{uuid.uuid4().hex[:8]}"
    sample_b64 = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVoxMjM0NTY3ODkw"

    monkeypatch.setattr("radcast.api.probe_duration_seconds", lambda path: 349.5)

    scheduled: list[str] = []

    def fake_schedule(job_id: str) -> None:
        scheduled.append(job_id)

    def fake_cancel(project_id_arg: str, *, reason: str):
        assert reason == "superseded by a newer request"
        return [
            {
                "job_id": "job_old",
                "status": "running",
                "assigned_worker_id": "wrk_b66a7fd434",
                "type": "enhance",
            }
        ]

    monkeypatch.setattr(radcast_api, "_schedule_worker_fallback_watch", fake_schedule)
    monkeypatch.setattr(radcast_api, "WORKER_FALLBACK_ENABLED", True)
    monkeypatch.setattr(radcast_api.worker_manager, "cancel_project_jobs", fake_cancel)
    monkeypatch.setattr(
        radcast_api,
        "_worker_availability_snapshot",
        lambda: {
            "worker_total_count": 1,
            "worker_online_count": 1,
            "worker_online_window_seconds": 60,
            "worker_summary": "1 live helper device",
        },
    )

    try:
        created = client.post("/projects", json={"project_id": project_id})
        assert created.status_code == 200

        uploaded = client.post(
            f"/projects/{project_id}/source-audio",
            json={"filename": "lecture.wav", "audio_b64": sample_b64},
        )
        assert uploaded.status_code == 200
        audio_hash = uploaded.json()["audio_hash"]

        response = client.post(
            "/enhance/simple",
            json={
                "project_id": project_id,
                "input_audio_hash": audio_hash,
                "output_format": "mp3",
                "enhancement_model": "none",
                "caption_format": "vtt",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["worker_mode"] is True
        assert payload["worker_fallback_timeout_seconds"] == 0
        assert scheduled == []
    finally:
        for path in Path("projects").glob(f"*__{project_id}"):
            if path.exists():
                shutil.rmtree(path)
        project_root = Path("projects") / project_id
        if project_root.exists():
            shutil.rmtree(project_root)


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


def test_enhance_simple_forwards_trim_values_into_worker_payload(monkeypatch):
    client = TestClient(app)
    project_id = f"radcast-{uuid.uuid4().hex[:8]}"
    sample_b64 = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVoxMjM0NTY3ODkw"
    captured: dict[str, object] = {}

    monkeypatch.setattr(radcast_api.worker_manager, "list_workers", lambda: [])
    monkeypatch.setattr(radcast_api.worker_manager, "cancel_project_jobs", lambda *args, **kwargs: [])
    monkeypatch.setattr("radcast.api.enhance_service.is_model_available", lambda _model: True)

    def fake_enqueue(req):
        captured["req"] = req
        return "job_trim"

    monkeypatch.setattr(radcast_api.worker_manager, "enqueue_enhance_job", fake_enqueue)

    try:
        created = client.post("/projects", json={"project_id": project_id})
        assert created.status_code == 200

        uploaded = client.post(
            f"/projects/{project_id}/source-audio",
            json={"filename": "lecture.wav", "audio_b64": sample_b64},
        )
        assert uploaded.status_code == 200
        audio_hash = uploaded.json()["audio_hash"]

        response = client.post(
            "/enhance/simple",
            json={
                "project_id": project_id,
                "input_audio_hash": audio_hash,
                "output_format": "mp3",
                "enhancement_model": "none",
                "clip_start_seconds": 1.5,
                "clip_end_seconds": 3.5,
            },
        )

        assert response.status_code == 200
        worker_req = captured["req"]
        assert worker_req.clip_start_seconds == 1.5
        assert worker_req.clip_end_seconds == 3.5
    finally:
        for path in Path("projects").glob(f"*__{project_id}"):
            if path.exists():
                shutil.rmtree(path)
        project_root = Path("projects") / project_id
        if project_root.exists():
            shutil.rmtree(project_root)


def test_enhance_simple_falls_back_to_saved_project_glossary(monkeypatch):
    client = TestClient(app)
    project_id = f"radcast-{uuid.uuid4().hex[:8]}"
    sample_b64 = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVoxMjM0NTY3ODkw"
    captured: dict[str, object] = {}

    monkeypatch.setattr(radcast_api.worker_manager, "list_workers", lambda: [])
    monkeypatch.setattr(radcast_api.worker_manager, "cancel_project_jobs", lambda *args, **kwargs: [])
    monkeypatch.setattr("radcast.api.enhance_service.is_model_available", lambda _model: True)
    monkeypatch.setattr(radcast_api.glossary_store, "active_terms_for_project", lambda _project_id: ["tikanga", "Aotearoa"])

    def fake_enqueue(req):
        captured["req"] = req
        return "job_glossary"

    monkeypatch.setattr(radcast_api.worker_manager, "enqueue_enhance_job", fake_enqueue)

    try:
        created = client.post("/projects", json={"project_id": project_id})
        assert created.status_code == 200

        updated = client.put(
            f"/projects/{project_id}/settings",
            json={
                "caption_glossary": "utu\nreciprocity\ntransgression\nmanaaki\nmanuhiri\nhaukāinga",
            },
        )
        assert updated.status_code == 200

        uploaded = client.post(
            f"/projects/{project_id}/source-audio",
            json={"filename": "lecture.wav", "audio_b64": sample_b64},
        )
        assert uploaded.status_code == 200
        audio_hash = uploaded.json()["audio_hash"]

        response = client.post(
            "/enhance/simple",
            json={
                "project_id": project_id,
                "input_audio_hash": audio_hash,
                "output_format": "mp3",
                "enhancement_model": "none",
                "caption_format": "vtt",
            },
        )

        assert response.status_code == 200
        worker_req = captured["req"]
        assert worker_req.caption_glossary == "utu, reciprocity, transgression, manaaki, manuhiri, haukāinga, tikanga, Aotearoa"
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
            "trim_ranges_by_audio_hash": {},
            "output_format": "mp3",
            "caption_format": None,
            "caption_quality_mode": "reviewed",
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
                "trim_ranges_by_audio_hash": {
                    audio_hash: {
                        "clip_start_seconds": 1.2,
                        "clip_end_seconds": 3.8,
                    }
                },
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
            "trim_ranges_by_audio_hash": {
                audio_hash: {
                    "clip_start_seconds": 1.2,
                    "clip_end_seconds": 3.8,
                }
            },
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
            runtime_seconds=644.0,
            output_format=OutputFormat.MP3,
            caption_file=caption_path,
            caption_review_file=review_path,
            caption_format=CaptionFormat.VTT,
            caption_review_required=True,
            caption_average_probability=0.63,
            caption_low_confidence_segments=3,
            caption_total_segments=12,
            caption_accessibility_status=CaptionAccessibilityStatus.FAILED,
            caption_review_warning_segments=1,
            caption_review_failure_segments=2,
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
        assert payload["outputs"][0]["runtime_seconds"] == 644.0
        assert payload["outputs"][0]["version_number"] == 1
        assert payload["outputs"][0]["caption_format"] == "vtt"
        assert payload["outputs"][0]["caption_download_url"].endswith("sample.vtt&download=true")
        assert payload["outputs"][0]["caption_review_required"] is True
        assert payload["outputs"][0]["caption_low_confidence_segments"] == 3
        assert payload["outputs"][0]["caption_accessibility_status"] == "failed"
        assert payload["outputs"][0]["caption_review_warning_segments"] == 1
        assert payload["outputs"][0]["caption_review_failure_segments"] == 2
        assert payload["outputs"][0]["caption_review_download_url"].endswith("sample.vtt.review.txt&download=true")
        assert payload["outputs"][0]["folder_path"].endswith("/assets/enhanced_audio")
    finally:
        for path in Path("projects").glob(f"*__{project_id}"):
            if path.exists():
                shutil.rmtree(path)
        if project_root and project_root.exists():
            shutil.rmtree(project_root)


def test_project_output_glossary_candidates_endpoint_returns_context():
    client = TestClient(app)
    project_id = f"radcast-{uuid.uuid4().hex[:8]}"
    project_root: Path | None = None

    try:
        created = client.post("/projects", json={"project_id": project_id})
        assert created.status_code == 200
        project_root = Path(created.json()["project_root"])

        manifests = project_root / "manifests"
        store = ManifestStore(manifests)
        output_path = project_root / "assets" / "enhanced_audio" / "simple.mp3"
        caption_path = project_root / "assets" / "enhanced_audio" / "simple.vtt"
        review_path = project_root / "assets" / "enhanced_audio" / "simple.vtt.review.txt"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        caption_path.write_text(
            "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nWelcome everyone\n\n00:00:01.000 --> 00:00:02.000\nAitikanga Māori space\n\n00:00:02.000 --> 00:00:03.000\nAnd then we discuss transgression\n",
            encoding="utf-8",
        )
        review_path.write_text(
            "RADcast Caption Review\n\nAverage word confidence: 89%\nFlagged caption lines: 2\nTotal caption lines: 3\n\nReview these timestamp ranges:\n\n00:00:01.000 --> 00:00:02.000 | confidence 91%\nReason: probable critical term miss: tikanga\nAitikanga Māori space\n\n00:00:02.000 --> 00:00:03.000 | confidence 88%\nReason: probable critical term miss: transgression\nAnd then we discuss transgression\n",
            encoding="utf-8",
        )
        output_path.write_bytes(b"fake-mp3")
        input_path = project_root / "assets" / "source_audio" / "simple.wav"
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_bytes(b"fake-wav")
        metadata = OutputMetadata(
            output_file=output_path,
            input_file=input_path,
            duration_seconds=3.0,
            runtime_seconds=12.0,
            output_format=OutputFormat.MP3,
            caption_file=caption_path,
            caption_review_file=review_path,
            caption_format=CaptionFormat.VTT,
            caption_review_required=True,
            caption_average_probability=0.89,
            caption_low_confidence_segments=0,
            caption_total_segments=3,
            caption_accessibility_status=CaptionAccessibilityStatus.FAILED,
            caption_review_warning_segments=0,
            caption_review_failure_segments=2,
            enhancement_model=EnhancementModel.RESEMBLE,
            audio_tuning_label="Version 1",
            project_id=project_id,
            job_id="job_test",
        )
        store.append_output(metadata)

        outputs = client.get(f"/projects/{project_id}/outputs")
        assert outputs.status_code == 200
        payload = outputs.json()
        assert payload["outputs"][0]["has_review_artifacts"] is True

        candidates = client.get(
            f"/projects/{project_id}/outputs/glossary-review-candidates",
            params={"path": payload["outputs"][0]["output_path"]},
        )
        assert candidates.status_code == 200
        candidate_payload = candidates.json()
        assert candidate_payload["project_id"] == project_id
        assert candidate_payload["output_path"].endswith("simple.mp3")
        assert candidate_payload["has_review_artifacts"] is True
        assert candidate_payload["has_candidates"] is True
        assert [row["normalized_term"] for row in candidate_payload["candidates"]] == ["tikanga", "transgression"]
        assert candidate_payload["candidates"][0]["previous_context"] == "Welcome everyone"
        assert candidate_payload["candidates"][0]["flagged_context"] == "Aitikanga Māori space"
        assert candidate_payload["candidates"][0]["next_context"] == "And then we discuss transgression"
    finally:
        for path in Path("projects").glob(f"*__{project_id}"):
            if path.exists():
                shutil.rmtree(path)
        if project_root and project_root.exists():
            shutil.rmtree(project_root)


def test_project_output_glossary_candidates_save_promotes_terms_to_global_store():
    client = TestClient(app)
    project_id = f"radcast-{uuid.uuid4().hex[:8]}"
    project_root: Path | None = None
    glossary_term = f"glossary-term-{uuid.uuid4().hex[:8]}"

    try:
        created = client.post("/projects", json={"project_id": project_id})
        assert created.status_code == 200
        project_root = Path(created.json()["project_root"])

        manifests = project_root / "manifests"
        store = ManifestStore(manifests)
        output_path = project_root / "assets" / "enhanced_audio" / "simple.mp3"
        caption_path = project_root / "assets" / "enhanced_audio" / "simple.vtt"
        review_path = project_root / "assets" / "enhanced_audio" / "simple.vtt.review.txt"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        caption_path.write_text("WEBVTT\n", encoding="utf-8")
        review_path.write_text(
            f"RADcast Caption Review\n\nAverage word confidence: 89%\nFlagged caption lines: 1\nTotal caption lines: 1\n\nReview these timestamp ranges:\n\n00:00:01.000 --> 00:00:02.000 | confidence 91%\nReason: probable critical term miss: {glossary_term}\nAitikanga Māori space\n",
            encoding="utf-8",
        )
        output_path.write_bytes(b"fake-mp3")
        input_path = project_root / "assets" / "source_audio" / "simple.wav"
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_bytes(b"fake-wav")
        metadata = OutputMetadata(
            output_file=output_path,
            input_file=input_path,
            duration_seconds=3.0,
            runtime_seconds=12.0,
            output_format=OutputFormat.MP3,
            caption_file=caption_path,
            caption_review_file=review_path,
            caption_format=CaptionFormat.VTT,
            caption_review_required=True,
            caption_average_probability=0.89,
            caption_low_confidence_segments=0,
            caption_total_segments=1,
            caption_accessibility_status=CaptionAccessibilityStatus.FAILED,
            caption_review_warning_segments=0,
            caption_review_failure_segments=1,
            enhancement_model=EnhancementModel.RESEMBLE,
            audio_tuning_label="Version 1",
            project_id=project_id,
            job_id="job_test",
        )
        store.append_output(metadata)

        outputs = client.get(f"/projects/{project_id}/outputs")
        payload = outputs.json()
        candidate_response = client.get(
            f"/projects/{project_id}/outputs/glossary-review-candidates",
            params={"path": payload["outputs"][0]["output_path"]},
        )
        candidate_payload = candidate_response.json()
        first_candidate = candidate_payload["candidates"][0]

        post_response = client.post(
            f"/projects/{project_id}/outputs/glossary-review-candidates",
            params={"path": payload["outputs"][0]["output_path"]},
            json={"approvals": [{"candidate_id": first_candidate["candidate_id"], "term": glossary_term}]},
        )
        assert post_response.status_code == 200
        post_payload = post_response.json()
        assert post_payload["project_id"] == project_id
        assert post_payload["output_path"].endswith("simple.mp3")
        assert post_payload["saved_terms"] == [glossary_term]
        assert post_payload["already_known_terms"] == []
        assert radcast_api.glossary_store.global_entries()[-1].normalized_term == radcast_api.normalize_glossary_term(glossary_term)
    finally:
        for path in Path("projects").glob(f"*__{project_id}"):
            if path.exists():
                shutil.rmtree(path)
        if project_root and project_root.exists():
            shutil.rmtree(project_root)
