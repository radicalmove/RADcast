"""Manifest persistence for jobs and outputs."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from radcast.models import JobRecord, OutputMetadata


class ManifestStore:
    def __init__(self, manifests_dir: Path):
        self.manifests_dir = manifests_dir
        self.jobs_file = manifests_dir / "jobs.json"
        self.outputs_file = manifests_dir / "outputs.json"
        self.caption_reviews_file = manifests_dir / "caption_reviews.json"
        self.manifests_dir.mkdir(parents=True, exist_ok=True)
        for path in (self.jobs_file, self.outputs_file, self.caption_reviews_file):
            if not path.exists():
                self._write(path, [])

    def list_jobs(self) -> list[dict[str, Any]]:
        return self._read(self.jobs_file)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        for item in self._read(self.jobs_file):
            if item.get("id") == job_id:
                return item
        return None

    def upsert_job(self, job: JobRecord) -> None:
        jobs = self._read(self.jobs_file)
        payload = job.model_dump(mode="json")
        replaced = False
        for idx, item in enumerate(jobs):
            if item.get("id") == job.id:
                jobs[idx] = payload
                replaced = True
                break
        if not replaced:
            jobs.append(payload)
        self._write(self.jobs_file, jobs)

    def append_output(self, metadata: OutputMetadata) -> None:
        items = self._read(self.outputs_file)
        items.append(metadata.model_dump(mode="json"))
        self._write(self.outputs_file, items)

    def list_outputs(self) -> list[dict[str, Any]]:
        return self._read(self.outputs_file)

    def list_caption_reviews(self) -> list[dict[str, Any]]:
        return self._read(self.caption_reviews_file)

    def write_caption_reviews(self, items: list[dict[str, Any]]) -> None:
        self._write(self.caption_reviews_file, items)

    def write_output_file(self, path: Path, metadata: OutputMetadata) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(metadata.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _read(path: Path) -> list[dict[str, Any]]:
        for attempt in range(3):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return []
            except json.JSONDecodeError:
                if attempt == 2:
                    return []
                time.sleep(0.01)
        return []

    @staticmethod
    def _write(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, default=str)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            finally:
                raise
