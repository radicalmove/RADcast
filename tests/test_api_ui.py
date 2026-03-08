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
