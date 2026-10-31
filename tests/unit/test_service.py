"""Tests for ``SessionService`` using the fake Word backend."""

import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from word_session.config import Settings
from word_session.events import Event
from word_session.model import DocumentState, Position, RestoreResult, Session
from word_session.service import (
    RestoreInProgress,
    RevisionConflict,
    SessionService,
    open_service,
)
from word_session.store import SessionNotFound
from word_session.word.backend import (
    DocumentLocked,
    DocumentMissing,
    WordError,
    WordNotResponding,
    WordUnavailable,
)
from word_session.word.fake import FakeDocument, FakeWordBackend

A = "C:\\Docs\\a.docx"
B = "C:\\Docs\\b.docx"


def _doc(path: str, *, active: bool = False, start: int | None = None) -> DocumentState:
    return DocumentState(
        path=path,
        location="local" if path[1:2] == ":" else "unsaved",
        active=active,
        position=Position(start=start, end=start),
    )


def _store_session(
    service: SessionService, docs: list[DocumentState], name: str = "S", kind: str = "manual"
) -> Session:
    created = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    session = Session.model_validate(
        {
            "id": service.store.new_id(created, name),
            "name": name,
            "kind": kind,
            "created_at": created,
            "documents": [d.model_dump(mode="json") for d in docs],
        }
    )
    service.store.save(session)
    return session


def _record(service: SessionService) -> list[Event]:
    events: list[Event] = []
    service.events.subscribe(events.append)
    return events


# ---- word_info / current ------------------------------------------------------


def test_word_info_does_not_connect(service: SessionService, fake_backend: FakeWordBackend) -> None:
    info = service.word_info()
    assert info.running
    assert fake_backend.calls == ["info"]


def test_current_lists_documents(service: SessionService) -> None:
    assert [d.path for d in service.current()] == [A, B]


def test_current_propagates_word_unavailable(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    fake_backend.running = False
    with pytest.raises(WordUnavailable):
        service.current()
    assert fake_backend.running is False


# ---- capture ------------------------------------------------------------------


def test_capture_saves_session_and_publishes(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    events = _record(service)
    result = service.capture()
    assert result.path is not None and result.path.is_file()
    assert result.session.name == "Session 2026-01-02 03:04"
    assert result.session.kind == "manual"
    assert result.session.host == "testhost"
    assert result.session.word_version == fake_backend.version
    assert result.warnings == []
    assert service.get(result.session.id).documents[1].active
    assert events == [{"type": "session_saved", "session_id": result.session.id, "kind": "manual"}]


def test_capture_auto_default_name_and_explicit_name(service: SessionService) -> None:
    assert service.capture(kind="auto").session.name == "Autosave 2026-01-02 03:04"
    assert service.capture("Mine").session.name == "Mine"


def test_capture_warns_for_unsaved_documents_and_changes(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    fake_backend.documents.append(FakeDocument(path="Document1"))
    fake_backend.documents[0].saved = False
    warnings = service.capture().warnings
    assert any("Document1" in w and "never saved" in w for w in warnings)
    assert any(A in w and "unsaved changes" in w for w in warnings)
    assert len(warnings) == 2


def test_capture_with_no_documents_saves_nothing(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    fake_backend.documents.clear()
    fake_backend.active_index = None
    events = _record(service)
    result = service.capture()
    assert result.path is None
    assert any("no open documents" in w for w in result.warnings)
    assert service.list_sessions() == []
    assert events == []


# ---- restore ------------------------------------------------------------------


def test_restore_orders_active_last_and_activates_it(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    c = "C:\\Docs\\c.docx"
    session = _store_session(service, [_doc(A, active=True), _doc(B), _doc(c)])
    fake_backend.documents.clear()
    fake_backend.active_index = None
    report = service.restore(session.id)
    assert [r.path for r in report.results] == [B, c, A]
    assert [r.status for r in report.results] == ["opened"] * 3
    assert report.ok and not report.dry_run
    assert fake_backend.active_index is not None
    assert fake_backend.documents[fake_backend.active_index].path == A
    assert fake_backend.calls[-1] == "activate"


def test_restore_events_in_order_with_keys_and_progress_callback(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    session = _store_session(service, [_doc(A), _doc(B, active=True)])
    fake_backend.documents.clear()
    events = _record(service)
    seen: list[RestoreResult] = []
    report = service.restore(session.id, progress=seen.append)
    assert [e["type"] for e in events] == [
        "restore_started",
        "restore_progress",
        "restore_progress",
        "restore_finished",
    ]
    assert events[0] == {"type": "restore_started", "session_id": session.id, "total": 2}
    assert events[1]["index"] == 0 and events[1]["total"] == 2
    assert events[2]["index"] == 1
    assert events[1]["result"] == {"path": A, "status": "opened", "message": ""}
    assert events[3]["report"] == report.model_dump(mode="json")
    assert seen == report.results


def test_restore_only_matches_globs_on_path_and_name(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    session = _store_session(service, [_doc(A), _doc(B), _doc("C:\\Other\\Note.docx")])
    fake_backend.documents.clear()
    by_name = service.restore(session.id, only=["A.DOCX"])
    assert [r.path for r in by_name.results] == [A]
    by_path = service.restore(session.id, only=["c:\\other\\*"])
    assert [r.path for r in by_path.results] == ["C:\\Other\\Note.docx"]
    assert service.restore(session.id, only=["*.pdf"]).results == []


def test_restore_unsaved_skipped_and_missing_without_word_call(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    session = _store_session(service, [_doc("Document1"), _doc("C:\\Docs\\missing.docx")])
    fake_backend.calls.clear()
    report = service.restore(session.id)
    assert [r.status for r in report.results] == ["skipped", "missing"]
    assert fake_backend.calls == []
    assert not report.ok


def test_restore_maps_word_errors_to_statuses_and_continues(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    paths = {
        "gone": "C:\\Docs\\gone.docx",
        "lock": "C:\\Docs\\lock.docx",
        "slow": "C:\\Docs\\slow.docx",
        "err": "C:\\Docs\\err.docx",
    }
    fake_backend.fail_paths = {
        paths["gone"]: DocumentMissing("File not found"),
        paths["lock"]: DocumentLocked("locked by someone"),
        paths["slow"]: WordNotResponding("too slow"),
        paths["err"]: WordError("boom"),
    }
    session = _store_session(service, [_doc(p) for p in paths.values()] + [_doc(A)])
    report = service.restore(session.id)
    assert [r.status for r in report.results] == [
        "missing",
        "locked",
        "failed",
        "failed",
        "already_open",
    ]
    assert report.results[2].message == "too slow"
    assert report.results[3].message == "boom"
    assert report.results[0].message == "File not found"


def test_restore_position_failure_keeps_status(
    service: SessionService, fake_backend: FakeWordBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _store_session(service, [_doc(A, start=5)])
    fake_backend.documents.clear()

    def broken(doc: DocumentState) -> None:
        raise WordError("cursor stuck")

    monkeypatch.setattr(fake_backend, "restore_position", broken)
    result = service.restore(session.id).results[0]
    assert result.status == "opened"
    assert result.message == "position not restored: cursor stuck"


def test_restore_position_applied_and_can_be_disabled(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    session = _store_session(service, [_doc(A, start=42)])
    fake_backend.documents.clear()
    service.restore(session.id)
    assert fake_backend.documents[0].position.start == 42

    fake_backend.documents.clear()
    service.restore(session.id, restore_position=False)
    assert fake_backend.documents[0].position.start is None


def test_restore_uses_settings_defaults(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    session = _store_session(service, [_doc(A)])
    fake_backend.documents.clear()
    fake_backend.running = False
    service.settings.restore.start_word = False
    with pytest.raises(WordUnavailable):
        service.restore(session.id)
    assert service.restore(session.id, start_word=True).results[0].status == "opened"


def test_restore_word_unavailable_before_any_document(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    session = _store_session(service, [_doc(A), _doc(B)])
    fake_backend.documents.clear()
    fake_backend.running = False
    events = _record(service)
    with pytest.raises(WordUnavailable):
        service.restore(session.id, start_word=False)
    assert events == []
    assert fake_backend.documents == []
    assert not service.restore_in_progress


def test_restore_dry_run_makes_no_backend_calls(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    session = _store_session(service, [_doc(A), _doc("Document1"), _doc("C:\\Docs\\missing.docx")])
    fake_backend.calls.clear()
    report = service.restore(session.id, dry_run=True)
    assert report.dry_run
    assert fake_backend.calls == []
    assert [r.status for r in report.results] == ["skipped", "skipped", "missing"]
    assert report.results[0].message == "dry run: would open"


def test_restore_in_progress_is_rejected_then_cleared(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    session = _store_session(service, [_doc(A)])
    fake_backend.documents.clear()
    hang = threading.Event()
    fake_backend.hang = hang
    outcome: list[object] = []

    def run() -> None:
        outcome.append(service.restore(session.id))

    thread = threading.Thread(target=run)
    thread.start()
    try:
        # Wait until the first restore has claimed the flag.
        while not service.restore_in_progress:
            threading.Event().wait(0.005)
        with pytest.raises(RestoreInProgress):
            service.restore(session.id)
        assert service.autosave_tick() is None
    finally:
        hang.set()
        thread.join(5)
    assert len(outcome) == 1
    assert not service.restore_in_progress
    service.restore(session.id)


# ---- listing, update, delete --------------------------------------------------


def test_list_sessions_filters_by_kind(service: SessionService) -> None:
    manual = _store_session(service, [_doc(A)], "m")
    auto = _store_session(service, [_doc(A)], "a", kind="auto")
    assert {s.id for s in service.list_sessions()} == {manual.id, auto.id}
    assert [s.id for s in service.list_sessions(kind="auto")] == [auto.id]
    assert service.revision(manual.id) == service.store.revision(manual.id)


def test_update_changes_only_given_fields(service: SessionService) -> None:
    session = _store_session(service, [_doc(A), _doc(B)], "orig")
    events = _record(service)
    updated = service.update(session.id, pinned=True, remove_paths=["c:\\docs\\A.DOCX"])
    assert updated.id == session.id
    assert updated.name == "orig" and updated.pinned and updated.notes == ""
    assert [d.path for d in updated.documents] == [B]
    assert service.get(session.id) == updated
    assert events == [{"type": "session_updated", "session_id": session.id}]

    renamed = service.update(session.id, name="New", notes="n")
    assert (renamed.name, renamed.notes, renamed.pinned) == ("New", "n", True)
    assert renamed.id == session.id


def test_update_stale_revision_conflicts_and_current_revision_works(
    service: SessionService,
) -> None:
    session = _store_session(service, [_doc(A)])
    old = service.revision(session.id)
    service.update(session.id, notes="first", expected_revision=old)
    events = _record(service)
    with pytest.raises(RevisionConflict):
        service.update(session.id, notes="second", expected_revision=old)
    assert service.get(session.id).notes == "first"
    assert events == []


def test_delete_trashes_or_purges_and_publishes(service: SessionService) -> None:
    first = _store_session(service, [_doc(A)], "one")
    second = _store_session(service, [_doc(A)], "two")
    events = _record(service)
    service.delete(first.id)
    service.delete(second.id, purge=True)
    assert (service.store.trash_dir / f"{first.id}.json").is_file()
    assert not (service.store.trash_dir / f"{second.id}.json").exists()
    assert events == [
        {"type": "session_deleted", "session_id": first.id},
        {"type": "session_deleted", "session_id": second.id},
    ]
    with pytest.raises(SessionNotFound):
        service.get(first.id)


def test_prune_defaults_to_settings_keep(service: SessionService) -> None:
    ids = [_store_session(service, [_doc(A)], f"a{i}", kind="auto").id for i in range(3)]
    service.settings.autosave.keep = 3
    assert service.prune() == []
    assert len(service.prune(keep=1)) == 2
    assert len(service.list_sessions()) == 1
    assert ids


def test_diff_ignores_case(service: SessionService) -> None:
    first = _store_session(service, [_doc(A), _doc(B)], "one")
    second = _store_session(service, [_doc(A.upper()), _doc("C:\\Docs\\c.docx")], "two")
    diff = service.diff(first.id, second.id)
    assert diff.added == ["C:\\Docs\\c.docx"]
    assert diff.removed == [B]


def test_import_legacy_uses_given_dirs(service: SessionService, tmp_path: Path) -> None:
    empty = tmp_path / "legacy"
    empty.mkdir()
    summary = service.import_legacy([empty])
    assert summary.imported == [] and summary.errors == []


# ---- autosave -----------------------------------------------------------------


def test_autosave_saves_then_skips_unchanged_then_saves_on_change(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    first = service.autosave_tick()
    assert first is not None and first.kind == "auto"
    assert service.autosave_tick() is None
    fake_backend.documents[0].position = Position(start=7, end=7)
    second = service.autosave_tick()
    assert second is not None and second.id != first.id
    assert len(service.list_sessions(kind="auto")) == 2


def test_autosave_without_only_on_change_always_saves(service: SessionService) -> None:
    service.settings.autosave.only_on_change = False
    assert service.autosave_tick() is not None
    assert service.autosave_tick() is not None


def test_autosave_prunes_to_keep(service: SessionService, fake_backend: FakeWordBackend) -> None:
    service.settings.autosave.keep = 1
    for i in range(3):
        fake_backend.documents[0].position = Position(start=i, end=i)
        assert service.autosave_tick() is not None
    assert len(service.list_sessions(kind="auto")) == 1


def test_autosave_skips_when_word_not_running_and_never_starts_it(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    fake_backend.running = False
    assert service.autosave_tick() is None
    assert fake_backend.running is False
    assert "connect" not in fake_backend.calls


def test_autosave_skips_without_documents_or_during_restore(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    service._restoring = True
    fake_backend.calls.clear()
    assert service.autosave_tick() is None
    assert fake_backend.calls == []
    service._restoring = False

    fake_backend.documents.clear()
    fake_backend.active_index = None
    assert service.autosave_tick() is None
    assert service.list_sessions() == []


def test_autosave_failure_publishes_event_and_returns_none(
    service: SessionService, fake_backend: FakeWordBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> list[DocumentState]:
        raise WordError("com exploded")

    monkeypatch.setattr(fake_backend, "list_documents", broken)
    events = _record(service)
    assert service.autosave_tick() is None
    assert events == [{"type": "autosave_failed", "message": "com exploded"}]


# ---- open_service / close -----------------------------------------------------


def test_open_service_fake_demo_roundtrip() -> None:
    service = open_service(settings=Settings(), fake=True)
    try:
        docs = service.current()
        assert len(docs) == 3
        assert all(d.path.startswith("C:\\Demo\\") for d in docs)
        result = service.capture("demo")
        assert result.path is not None
        report = service.restore(result.session.id)
        assert report.ok
    finally:
        service.close()
