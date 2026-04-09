"""Persistent glossary storage for caption terminology."""

from __future__ import annotations

import json
import os
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from radcast.models import GlossaryEntry, GlossaryScope, GlossaryStatus
from radcast.project import ProjectManager

_GLOBAL_PROJECT_ID = "_global"


@dataclass(frozen=True)
class GlossaryLocation:
    scope: GlossaryScope
    project_id: str | None
    path: Path


class GlossaryStore:
    def __init__(self, projects_root: Path | str = Path("projects")):
        self.project_manager = ProjectManager(projects_root)

    def global_entries(self) -> list[GlossaryEntry]:
        return self._read_entries(self.project_manager.global_glossary_path(), GlossaryScope.GLOBAL)

    def project_entries(self, project_id: str) -> list[GlossaryEntry]:
        return self._read_entries(self.project_manager.glossary_path(project_id), GlossaryScope.PROJECT, project_id)

    def active_terms_for_project(self, project_id: str) -> list[str]:
        ordered_terms: list[str] = []
        seen: set[str] = set()
        project_entries = [
            entry
            for entry in self.project_entries(project_id)
            if entry.status == GlossaryStatus.ACTIVE
        ]
        global_entries = [
            entry
            for entry in self.global_entries()
            if entry.status == GlossaryStatus.ACTIVE
        ]
        for entry in [*project_entries, *global_entries]:
            if entry.normalized_term in seen:
                continue
            seen.add(entry.normalized_term)
            ordered_terms.append(entry.term)
        return ordered_terms

    def effective_entries_for_project(self, project_id: str) -> list[GlossaryEntry]:
        entries: list[GlossaryEntry] = []
        seen: set[str] = set()
        for entry in self.project_entries(project_id):
            if entry.status != GlossaryStatus.ACTIVE or entry.normalized_term in seen:
                continue
            seen.add(entry.normalized_term)
            entries.append(entry)
        for entry in self.global_entries():
            if entry.status != GlossaryStatus.ACTIVE or entry.normalized_term in seen:
                continue
            seen.add(entry.normalized_term)
            entries.append(entry)
        return entries

    def upsert_entry(self, entry: GlossaryEntry) -> GlossaryEntry:
        location = self._location_for_entry(entry)
        entries = self._read_entries(location.path, location.scope, location.project_id)
        replaced = False
        now = datetime.now(timezone.utc)
        for idx, current in enumerate(entries):
            if current.normalized_term == entry.normalized_term:
                updated = current.model_copy(
                    update={
                        "term": entry.term,
                        "normalized_term": entry.normalized_term,
                        "scope": entry.scope,
                        "project_id": entry.project_id,
                        "status": entry.status,
                        "notes": list(entry.notes),
                        "updated_at": now,
                    }
                )
                entries[idx] = updated
                replaced = True
                break
        if not replaced:
            entry = entry.model_copy(update={"updated_at": now})
            entries.append(entry)
        self._write_entries(location.path, entries)
        for current in self._read_entries(location.path, location.scope, location.project_id):
            if current.normalized_term == entry.normalized_term:
                return current
        return entry

    def set_status(
        self,
        *,
        term: str,
        status: GlossaryStatus,
        scope: GlossaryScope,
        project_id: str | None = None,
        notes: list[str] | None = None,
    ) -> GlossaryEntry:
        normalized_term = normalize_glossary_term(term)
        location = self._location(scope=scope, project_id=project_id)
        entries = self._read_entries(location.path, location.scope, location.project_id)
        for idx, current in enumerate(entries):
            if current.normalized_term == normalized_term:
                updated = current.model_copy(
                    update={
                        "status": status,
                        "notes": list(notes or current.notes),
                        "updated_at": datetime.now(timezone.utc),
                    }
                )
                entries[idx] = updated
                self._write_entries(location.path, entries)
                return updated
        created = GlossaryEntry(
            term=term.strip(),
            normalized_term=normalized_term,
            scope=scope,
            project_id=project_id,
            status=status,
            notes=list(notes or []),
        )
        self._write_entries(location.path, [*entries, created])
        return created

    def import_legacy_caption_glossary(
        self,
        value: str | None,
        *,
        project_id: str | None = None,
        scope: GlossaryScope = GlossaryScope.PROJECT,
    ) -> list[GlossaryEntry]:
        parsed_terms = split_legacy_glossary_terms(value)
        if not parsed_terms:
            return []
        imported: list[GlossaryEntry] = []
        for raw_term in parsed_terms:
            normalized = normalize_glossary_term(raw_term)
            if not normalized:
                continue
            imported.append(
                GlossaryEntry(
                    term=raw_term,
                    normalized_term=normalized,
                    scope=scope,
                    project_id=project_id if scope == GlossaryScope.PROJECT else None,
                    status=GlossaryStatus.SUGGESTED,
                    notes=["legacy-import"],
                )
            )
        if not imported and value and value.strip():
            imported.append(
                GlossaryEntry(
                    term=value.strip(),
                    normalized_term=normalize_glossary_term(value),
                    scope=scope,
                    project_id=project_id if scope == GlossaryScope.PROJECT else None,
                    status=GlossaryStatus.SUGGESTED,
                    notes=["legacy-import"],
                )
            )
        for entry in imported:
            self.upsert_entry(entry)
        return imported

    def list_all_entries(self) -> list[GlossaryEntry]:
        return [*self.global_entries()]

    def _location_for_entry(self, entry: GlossaryEntry) -> GlossaryLocation:
        return self._location(scope=entry.scope, project_id=entry.project_id)

    def _location(self, *, scope: GlossaryScope, project_id: str | None) -> GlossaryLocation:
        if scope == GlossaryScope.GLOBAL:
            return GlossaryLocation(scope=scope, project_id=None, path=self.project_manager.global_glossary_path())
        if not project_id:
            raise ValueError("project_id is required for project-scoped glossary entries")
        return GlossaryLocation(scope=scope, project_id=project_id, path=self.project_manager.glossary_path(project_id))

    @staticmethod
    def _read_entries(path: Path, scope: GlossaryScope, project_id: str | None = None) -> list[GlossaryEntry]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except json.JSONDecodeError:
            return []
        if isinstance(payload, dict):
            payload = payload.get("entries", [])
        if not isinstance(payload, list):
            return []
        entries: list[GlossaryEntry] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            payload_item = dict(item)
            payload_item.setdefault("scope", scope.value)
            payload_item.setdefault("project_id", project_id)
            try:
                entries.append(GlossaryEntry.model_validate(payload_item))
            except Exception:
                continue
        return entries

    @staticmethod
    def _write_entries(path: Path, entries: list[GlossaryEntry]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"entries": [entry.model_dump(mode="python") for entry in entries], "updated_at": datetime.now(timezone.utc).isoformat()}
        fd, temp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, default=str)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)


def normalize_glossary_term(term: str) -> str:
    text = unicodedata.normalize("NFKD", str(term or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = " ".join(text.split())
    return text.strip()


def split_legacy_glossary_terms(value: str | None) -> list[str]:
    if not value:
        return []
    text = value.strip()
    if not text:
        return []
    terms: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for char in text:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
            current.append(char)
            continue
        if char in {",", ";", "\n"}:
            candidate = _clean_legacy_token("".join(current))
            if candidate:
                terms.append(candidate)
            current = []
            continue
        current.append(char)
    candidate = _clean_legacy_token("".join(current))
    if candidate:
        terms.append(candidate)
    if not terms and text:
        return [_clean_legacy_token(text) or text]
    return terms


def _clean_legacy_token(value: str) -> str:
    token = value.strip()
    token = token.strip(" \t\r\n,;:()[]{}")
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
        token = token[1:-1].strip()
    return token
