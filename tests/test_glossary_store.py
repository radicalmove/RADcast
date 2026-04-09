from __future__ import annotations

from pathlib import Path

from radcast.models import GlossaryEntry, GlossaryScope, GlossaryStatus
from radcast.project import ProjectManager
from radcast.services.glossary_store import GlossaryStore, normalize_glossary_term, split_legacy_glossary_terms


def test_glossary_store_merges_scope_and_status(tmp_path: Path) -> None:
    manager = ProjectManager(tmp_path / "projects")
    manager.create_project("crju150")
    store = GlossaryStore(tmp_path / "projects")

    store.upsert_entry(
        GlossaryEntry(
            term="tikanga",
            normalized_term=normalize_glossary_term("tikanga"),
            scope=GlossaryScope.GLOBAL,
            status=GlossaryStatus.ACTIVE,
        )
    )
    store.upsert_entry(
        GlossaryEntry(
            term="manaaki",
            normalized_term=normalize_glossary_term("manaaki"),
            scope=GlossaryScope.GLOBAL,
            status=GlossaryStatus.ACTIVE,
        )
    )
    store.upsert_entry(
        GlossaryEntry(
            term="manaaki",
            normalized_term=normalize_glossary_term("manaaki"),
            scope=GlossaryScope.PROJECT,
            project_id="crju150",
            status=GlossaryStatus.ACTIVE,
        )
    )

    assert store.active_terms_for_project("crju150") == ["manaaki", "tikanga"]
    assert [entry.term for entry in store.effective_entries_for_project("crju150")] == [
        "manaaki",
        "tikanga",
    ]


def test_glossary_store_duplicate_dedupe_and_lifecycle(tmp_path: Path) -> None:
    store = GlossaryStore(tmp_path / "projects")

    created = store.upsert_entry(
        GlossaryEntry(
            term="Whānau",
            normalized_term=normalize_glossary_term("Whānau"),
            scope=GlossaryScope.GLOBAL,
            status=GlossaryStatus.SUGGESTED,
        )
    )
    updated = store.upsert_entry(
        GlossaryEntry(
            term="whanau",
            normalized_term=normalize_glossary_term("whanau"),
            scope=GlossaryScope.GLOBAL,
            status=GlossaryStatus.ACTIVE,
            notes=["promoted"],
        )
    )

    assert created.normalized_term == "whanau"
    assert updated.status == GlossaryStatus.ACTIVE
    assert updated.notes == ["promoted"]
    assert [entry.normalized_term for entry in store.global_entries()] == ["whanau"]

    disabled = store.set_status(
        term="whanau",
        status=GlossaryStatus.DISABLED,
        scope=GlossaryScope.GLOBAL,
    )
    assert disabled.status == GlossaryStatus.DISABLED
    assert store.global_entries()[0].status == GlossaryStatus.DISABLED


def test_glossary_store_legacy_import_splits_and_normalizes(tmp_path: Path) -> None:
    store = GlossaryStore(tmp_path / "projects")
    imported = store.import_legacy_caption_glossary(
        '"Tikanga Māori"; manaaki, kaitiaki\nWhānau',
        project_id="crju150",
    )

    assert [entry.term for entry in imported] == [
        "Tikanga Māori",
        "manaaki",
        "kaitiaki",
        "Whānau",
    ]
    assert [entry.normalized_term for entry in imported] == [
        "tikanga maori",
        "manaaki",
        "kaitiaki",
        "whanau",
    ]
    assert all(entry.status == GlossaryStatus.SUGGESTED for entry in imported)
    assert all(entry.project_id == "crju150" for entry in imported)


def test_glossary_store_legacy_import_falls_back_for_ambiguous_string(tmp_path: Path) -> None:
    store = GlossaryStore(tmp_path / "projects")
    imported = store.import_legacy_caption_glossary('"""', project_id="crju150")

    assert len(imported) == 1
    assert imported[0].status == GlossaryStatus.SUGGESTED
    assert imported[0].notes == ["legacy-import"]
    assert imported[0].project_id == "crju150"


def test_glossary_path_helpers_expose_global_manifest(tmp_path: Path) -> None:
    manager = ProjectManager(tmp_path / "projects")

    assert manager.global_root().name == "_global"
    assert manager.global_glossary_path() == tmp_path / "projects" / "_global" / "manifests" / "glossary.json"
    assert manager.glossary_path("crju150") == tmp_path / "projects" / "crju150" / "manifests" / "glossary.json"


def test_split_legacy_glossary_terms_preserves_quotes_and_separators() -> None:
    assert split_legacy_glossary_terms('"A B", C;D\nE') == ["A B", "C", "D", "E"]
