"""Tests for the file-backed session store."""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from word_session.model import DocumentState, Session
from word_session.store import AmbiguousSelector, SessionNotFound, SessionStore, StoreError

TZ = timezone(timedelta(hours=1))
BASE = datetime(2026, 10, 31, 14, 30, 0, tzinfo=TZ)


def make_session(**overrides: Any) -> Session:
    fields: dict[str, Any] = {
        "id": "20261031T143000-alpha",
        "name": "Alpha",
        "kind": "manual",
        "created_at": BASE,
        "documents": [DocumentState(path="C:\\Thèse\\ch1.docx", location="local")],
    }
    fields.update(overrides)
    return Session(**fields)


def at(minutes: int, name: str, **overrides: Any) -> Session:
    created = BASE + timedelta(minutes=minutes)
    sid = f"{created:%Y%m%dT%H%M%S}-{name.lower()}"
    return make_session(id=sid, name=name, created_at=created, **overrides)


@pytest.fixture
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path / "sessions")


def test_round_trip_and_format(store: SessionStore) -> None:
    session = make_session()
    path = store.save(session)
    assert path == store.root / "20261031T143000-alpha.json"
    raw = path.read_bytes()
    assert raw.endswith(b"\n") and b"\r" not in raw
    assert "Thèse".encode() in raw
    assert store.load_file(path) == session


def test_save_overwrites(store: SessionStore) -> None:
    store.save(make_session())
    store.save(make_session(name="Renamed", pinned=True))
    loaded = store.get("20261031T143000-alpha")
    assert loaded.name == "Renamed" and loaded.pinned


def test_save_is_atomic(store: SessionStore, monkeypatch: pytest.MonkeyPatch) -> None:
    path = store.save(make_session())
    before = path.read_bytes()

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("disk gone")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        store.save(make_session(name="Changed"))
    monkeypatch.undo()

    assert path.read_bytes() == before
    assert list(store.root.glob("*.tmp")) == []


def test_new_id_collisions(store: SessionStore) -> None:
    first = store.new_id(BASE, "Alpha")
    assert first == "20261031T143000-alpha"
    store.save(make_session(id=first))
    assert store.new_id(BASE, "Alpha") == first + "-2"
    store.save(make_session(id=first + "-2"))
    assert store.new_id(BASE, "Alpha") == first + "-3"

    # A trashed file also reserves its id.
    store.delete(first + "-2")
    store.delete(first)
    assert store.new_id(BASE, "Alpha") == first + "-3"


def test_list_order_and_ignored_files(store: SessionStore) -> None:
    for minutes, name in [(0, "Old"), (10, "New"), (5, "Mid")]:
        store.save(at(minutes, name))
    (store.root / "stray.json.tmp").write_text("{}", encoding="utf-8")
    (store.root / "notes.txt").write_text("hi", encoding="utf-8")
    store.delete(at(0, "Old").id)

    assert [s.name for s in store.list()] == ["New", "Mid"]


def test_invalid_files_skipped_and_reported(
    store: SessionStore, caplog: pytest.LogCaptureFixture
) -> None:
    store.save(make_session())
    bad_json = store.root / "bad.json"
    bad_json.write_text("{not json", encoding="utf-8")
    bad_schema = store.root / "schema.json"
    bad_schema.write_text(json.dumps({"id": "x"}), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="word_session.store"):
        sessions = store.list()
    assert len(sessions) == 1
    assert "bad.json" in caplog.text

    invalid = dict(store.list_invalid())
    assert set(invalid) == {bad_json, bad_schema}
    assert "invalid JSON" in invalid[bad_json]
    assert "bad.json" in invalid[bad_json]


def test_load_file_errors_name_path(store: SessionStore, tmp_path: Path) -> None:
    with pytest.raises(StoreError, match=r"missing\.json"):
        store.load_file(tmp_path / "missing.json")


def test_empty_store(store: SessionStore) -> None:
    assert store.list() == []
    with pytest.raises(SessionNotFound, match="no sessions in"):
        store.get("latest")


@pytest.fixture
def populated(store: SessionStore) -> SessionStore:
    store.save(at(0, "Oldest", kind="manual"))
    store.save(at(10, "Middle", kind="auto"))
    store.save(at(20, "Newest", kind="auto"))
    store.save(at(30, "Shared", kind="manual"))
    store.save(at(31, "shared", kind="manual"))
    return store


def test_selector_latest_variants(populated: SessionStore) -> None:
    assert populated.get("latest").name == "shared"
    assert populated.get("latest-manual").name == "shared"
    assert populated.get("latest-auto").name == "Newest"


def test_selector_latest_kind_missing(store: SessionStore) -> None:
    store.save(at(0, "Only", kind="manual"))
    with pytest.raises(SessionNotFound, match="latest-auto"):
        store.get("latest-auto")


def test_selector_negative_index(populated: SessionStore) -> None:
    assert populated.get("-1").name == "shared"
    assert populated.get("-3").name == "Newest"
    with pytest.raises(SessionNotFound, match="-9"):
        populated.get("-9")


def test_selector_file_path(populated: SessionStore, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere.json"
    outside.write_text(json.dumps(make_session(name="External").model_dump(mode="json")))
    assert populated.get(str(outside)).name == "External"


def test_selector_exact_id(populated: SessionStore) -> None:
    assert populated.get(at(0, "Oldest").id).name == "Oldest"


def test_selector_name_case_insensitive(populated: SessionStore) -> None:
    assert populated.get("MIDDLE").name == "Middle"


def test_selector_ambiguous_name(populated: SessionStore) -> None:
    with pytest.raises(AmbiguousSelector) as info:
        populated.get("SHARED")
    assert len(info.value.candidates) == 2


def test_selector_prefix(populated: SessionStore) -> None:
    assert populated.get("20261031T1450").name == "Newest"
    with pytest.raises(AmbiguousSelector) as info:
        populated.get("20261031T")
    assert len(info.value.candidates) == 5


def test_selector_not_found(populated: SessionStore) -> None:
    with pytest.raises(SessionNotFound, match="nothing-here"):
        populated.get("nothing-here")
    # Prefixes shorter than four characters are not considered.
    with pytest.raises(SessionNotFound, match="202"):
        populated.get("202")


def test_revision_changes(store: SessionStore) -> None:
    store.save(make_session())
    first = store.revision("20261031T143000-alpha")
    assert first == store.revision("20261031T143000-alpha")
    store.save(make_session(notes="edited"))
    assert store.revision("20261031T143000-alpha") != first
    with pytest.raises(SessionNotFound):
        store.revision("nope")


def test_delete_to_trash_and_overwrite(store: SessionStore) -> None:
    session = make_session()
    store.save(session)
    store.delete(session.id)
    assert not store.path_for(session.id).exists()
    assert (store.trash_dir / f"{session.id}.json").is_file()

    # Deleting a second file of the same name overwrites the trashed copy.
    store.save(make_session(notes="second"))
    store.delete(session.id)
    trashed = json.loads((store.trash_dir / f"{session.id}.json").read_text(encoding="utf-8"))
    assert trashed["notes"] == "second"


def test_delete_purge_and_unknown(store: SessionStore) -> None:
    session = make_session()
    store.save(session)
    store.delete(session.id, purge=True)
    assert not store.path_for(session.id).exists()
    assert not store.trash_dir.exists()
    with pytest.raises(SessionNotFound):
        store.delete(session.id)
    with pytest.raises(StoreError):
        store.delete("../escape")


def test_prune(store: SessionStore) -> None:
    for minutes in range(5):
        store.save(at(minutes, f"auto{minutes}", kind="auto"))
    store.save(at(10, "manual", kind="manual"))
    store.save(at(-5, "pinned", kind="auto", pinned=True))

    removed = store.prune(2)
    assert removed == [at(2, "auto2").id, at(1, "auto1").id, at(0, "auto0").id]
    remaining = {s.name for s in store.list()}
    assert remaining == {"auto3", "auto4", "manual", "pinned"}
    assert (store.trash_dir / f"{at(0, 'auto0').id}.json").is_file()

    assert store.prune(2) == []
    assert store.prune(0) == [at(4, "auto4").id, at(3, "auto3").id]
    assert {s.name for s in store.list()} == {"manual", "pinned"}


def test_prune_negative(store: SessionStore) -> None:
    with pytest.raises(ValueError):
        store.prune(-1)
