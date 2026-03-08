from __future__ import annotations

import json
from pathlib import Path

from radcast.manifests import ManifestStore
from radcast.models import JobRecord, JobStatus


def test_manifest_store_read_retries_after_transient_json_decode(monkeypatch, tmp_path):
    target = tmp_path / "jobs.json"
    target.write_text(json.dumps([{"id": "job_1"}]), encoding="utf-8")

    original_read_text = Path.read_text
    calls = {"count": 0}

    def flaky_read_text(self, *args, **kwargs):
        if self == target and calls["count"] == 0:
            calls["count"] += 1
            return "{"
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    monkeypatch.setattr("radcast.manifests.time.sleep", lambda _seconds: None)

    assert ManifestStore._read(target) == [{"id": "job_1"}]


def test_manifest_store_upsert_and_get_job_roundtrip(tmp_path):
    store = ManifestStore(tmp_path)
    job = JobRecord(
        id="job_1",
        project_id="project_a",
        status=JobStatus.RUNNING,
        stage="enhance",
        progress=0.4,
    )

    store.upsert_job(job)

    payload = store.get_job("job_1")
    assert payload is not None
    assert payload["id"] == "job_1"
    assert payload["project_id"] == "project_a"
