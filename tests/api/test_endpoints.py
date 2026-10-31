"""Endpoint tests: happy paths, error mappings and the ETag/If-Match flow."""

import sys
import types
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from word_session import shortcut
from word_session.config import AppPaths, load_settings
from word_session.model import DocumentState, Session
from word_session.service import SessionService
from word_session.word.backend import WordError, WordNotResponding
from word_session.word.fake import FakeWordBackend

A = "C:\\Docs\\a.docx"


def _store(
    service: SessionService, name: str, paths: list[str], *, pinned: bool = False
) -> Session:
    """Save a session with the given document paths directly in the store."""
    created = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    docs = [
        DocumentState(path=p, location="url" if p.startswith("http") else "local").model_dump(
            mode="json"
        )
        for p in paths
    ]
    session = Session.model_validate(
        {
            "id": service.store.new_id(created, name),
            "name": name,
            "kind": "manual",
            "pinned": pinned,
            "created_at": created,
            "documents": docs,
        }
    )
    service.store.save(session)
    return session


# ---- Word -----------------------------------------------------------------------


def test_word_info(client: TestClient) -> None:
    body = client.get("/api/word").json()
    assert body["running"] is True


def test_word_documents(client: TestClient) -> None:
    body = client.get("/api/word/documents").json()
    assert [d["path"] for d in body] == [A, "C:\\Docs\\b.docx"]


def test_word_documents_unavailable_is_503(
    client: TestClient, fake_backend: FakeWordBackend
) -> None:
    fake_backend.running = False
    response = client.get("/api/word/documents")
    assert response.status_code == 503
    assert response.json()["error"]["type"] == "WordUnavailable"


# ---- listing --------------------------------------------------------------------


def test_list_sessions_and_missing_count(client: TestClient, service: SessionService) -> None:
    session = _store(service, "Thesis", [A, "C:\\Docs\\missing.docx", "https://x/y.docx"])
    (row,) = client.get("/api/sessions").json()
    assert row["id"] == session.id
    assert row["document_count"] == 3
    assert row["missing_count"] == 1


def test_list_filters(client: TestClient, service: SessionService) -> None:
    thesis = _store(service, "Thesis", [A], pinned=True)
    _store(service, "Invoices", ["C:\\Money\\Q1.docx"])
    ids = lambda params: [s["id"] for s in client.get("/api/sessions", params=params).json()]  # noqa: E731
    assert ids({"q": "THESIS"}) == [thesis.id]
    assert ids({"q": "money"}) != [thesis.id] and len(ids({"q": "money"})) == 1
    assert ids({"pinned": "true"}) == [thesis.id]
    assert len(ids({"pinned": "false"})) == 1
    assert ids({"kind": "auto"}) == []
    assert len(ids({"kind": "manual"})) == 2


# ---- capture --------------------------------------------------------------------


def test_capture_creates_session(client: TestClient, service: SessionService) -> None:
    response = client.post("/api/sessions", json={"name": "Mine"})
    assert response.status_code == 201
    body = response.json()
    assert body["saved"] is True
    assert body["session"]["name"] == "Mine"
    assert service.get(body["session"]["id"]).name == "Mine"


def test_capture_with_paths_and_close(client: TestClient, fake_backend: FakeWordBackend) -> None:
    path = fake_backend.documents[0].path
    body = client.post("/api/sessions", json={"name": "Some", "paths": [path]}).json()
    assert [d["path"] for d in body["session"]["documents"]] == [path]
    results = client.post("/api/word/close", json={"paths": [path]}).json()
    assert [r["status"] for r in results] == ["closed"]
    assert all(d.path != path for d in fake_backend.documents)


def test_capture_without_body_uses_default_name(client: TestClient) -> None:
    response = client.post("/api/sessions")
    assert response.status_code == 201
    assert response.json()["session"]["name"]


def test_capture_with_no_documents_is_200_and_not_saved(
    client: TestClient, fake_backend: FakeWordBackend, service: SessionService
) -> None:
    fake_backend.documents.clear()
    response = client.post("/api/sessions", json={"name": None})
    assert response.status_code == 200
    assert response.json()["saved"] is False
    assert service.list_sessions() == []


def test_capture_word_not_running_is_503(client: TestClient, fake_backend: FakeWordBackend) -> None:
    fake_backend.running = False
    fake_backend.installed = False
    assert client.post("/api/sessions").status_code == 503


# ---- detail, ETag, patch, delete -----------------------------------------------------


def test_detail_has_etag_and_existence(client: TestClient, service: SessionService) -> None:
    session = _store(service, "Thesis", [A, "C:\\Docs\\missing.docx", "https://x/y.docx"])
    response = client.get(f"/api/sessions/{session.id}")
    assert response.status_code == 200
    body = response.json()
    assert response.headers["etag"] == f'"{body["revision"]}"'
    assert [d["exists"] for d in body["documents"]] == [True, False, None]


def test_unknown_session_is_404(client: TestClient) -> None:
    response = client.get("/api/sessions/nope")
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "SessionNotFound"


def test_prefix_of_id_is_404(client: TestClient, service: SessionService) -> None:
    session = _store(service, "Thesis", [A])
    assert client.get(f"/api/sessions/{session.id[:12]}").status_code == 404
    assert client.get(f"/api/sessions/{session.id}").status_code == 200


def test_ambiguous_selector_is_409(client: TestClient, service: SessionService) -> None:
    _store(service, "Alpha", [A])
    _store(service, "Alpine", [A])
    response = client.get("/api/sessions/20260501T100000")
    assert response.status_code == 409
    assert response.json()["error"]["type"] == "AmbiguousSelector"


def test_patch_requires_if_match(client: TestClient, service: SessionService) -> None:
    session = _store(service, "Thesis", [A])
    response = client.patch(f"/api/sessions/{session.id}", json={"name": "New"})
    assert response.status_code == 428


def test_patch_with_stale_etag_is_412(client: TestClient, service: SessionService) -> None:
    session = _store(service, "Thesis", [A])
    response = client.patch(
        f"/api/sessions/{session.id}", json={"name": "New"}, headers={"If-Match": '"stale"'}
    )
    assert response.status_code == 412
    assert response.json()["error"]["type"] == "RevisionConflict"
    assert service.get(session.id).name == "Thesis"


def test_patch_flow_returns_new_etag(client: TestClient, service: SessionService) -> None:
    session = _store(service, "Thesis", [A, "C:\\Docs\\b.docx"])
    first = client.get(f"/api/sessions/{session.id}")
    response = client.patch(
        f"/api/sessions/{session.id}",
        json={"name": "Renamed", "pinned": True, "notes": "n", "remove_paths": [A.lower()]},
        headers={"If-Match": first.headers["etag"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed"
    assert body["pinned"] is True
    assert body["notes"] == "n"
    assert [d["path"] for d in body["documents"]] == ["C:\\Docs\\b.docx"]
    assert response.headers["etag"] != first.headers["etag"]
    assert response.headers["etag"] == f'"{body["revision"]}"'
    # The old ETag is now stale.
    again = client.patch(
        f"/api/sessions/{session.id}",
        json={"name": "X"},
        headers={"If-Match": first.headers["etag"]},
    )
    assert again.status_code == 412


def test_patch_rejects_unknown_fields(client: TestClient, service: SessionService) -> None:
    session = _store(service, "Thesis", [A])
    etag = client.get(f"/api/sessions/{session.id}").headers["etag"]
    response = client.patch(
        f"/api/sessions/{session.id}", json={"id": "x"}, headers={"If-Match": etag}
    )
    assert response.status_code == 422


def test_delete_requires_if_match_and_moves_to_trash(
    client: TestClient, service: SessionService
) -> None:
    session = _store(service, "Thesis", [A])
    assert client.delete(f"/api/sessions/{session.id}").status_code == 428
    assert (
        client.delete(f"/api/sessions/{session.id}", headers={"If-Match": '"x"'}).status_code == 412
    )
    etag = client.get(f"/api/sessions/{session.id}").headers["etag"]
    response = client.delete(f"/api/sessions/{session.id}", headers={"If-Match": etag})
    assert response.status_code == 204
    assert client.get(f"/api/sessions/{session.id}").status_code == 404


def test_delete_with_purge(client: TestClient, service: SessionService) -> None:
    session = _store(service, "Thesis", [A])
    etag = client.get(f"/api/sessions/{session.id}").headers["etag"]
    response = client.delete(f"/api/sessions/{session.id}?purge=true", headers={"If-Match": etag})
    assert response.status_code == 204
    assert service.list_sessions() == []


# ---- restore and jobs (the lifecycle is covered in test_jobs_sse) ------------------


def test_restore_unknown_session_is_404(client: TestClient) -> None:
    assert client.post("/api/sessions/nope/restore", json={}).status_code == 404


def test_restore_rejects_unknown_fields(client: TestClient, service: SessionService) -> None:
    session = _store(service, "Thesis", [A])
    assert client.post(f"/api/sessions/{session.id}/restore", json={"x": 1}).status_code == 422


def test_unknown_job_is_404(client: TestClient) -> None:
    response = client.get("/api/jobs/nope")
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "JobNotFound"


# ---- settings -------------------------------------------------------------------


def test_settings_round_trip(client: TestClient, service: SessionService) -> None:
    current = client.get("/api/settings").json()
    assert current["autosave"]["interval_minutes"] == 10
    current["autosave"]["interval_minutes"] = 30
    response = client.put("/api/settings", json=current)
    assert response.status_code == 200
    assert service.settings.autosave.interval_minutes == 30
    assert load_settings().autosave.interval_minutes == 30
    assert client.get("/api/settings").json()["autosave"]["interval_minutes"] == 30


def test_invalid_settings_put_is_422(client: TestClient, service: SessionService) -> None:
    current = client.get("/api/settings").json()
    current["autosave"]["interval_minutes"] = 0
    assert client.put("/api/settings", json=current).status_code == 422
    assert service.settings.autosave.interval_minutes == 10


def test_unknown_settings_key_is_422(client: TestClient) -> None:
    assert client.put("/api/settings", json={"bogus": 1}).status_code == 422


# ---- doctor, logs ---------------------------------------------------------


def test_doctor_without_module_is_empty(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("importlib.import_module", _missing_module)
    assert client.get("/api/doctor").json() == []


def _missing_module(name: str) -> types.ModuleType:
    raise ModuleNotFoundError(name)


def test_doctor_lists_checks(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    @dataclass
    class Check:
        name: str
        status: str
        detail: str

    fake = types.ModuleType("word_session.doctor")

    def run_checks(service: SessionService, paths: AppPaths) -> list[Check]:
        return [Check("python", "ok", "3.13")]

    fake.run_checks = run_checks  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "word_session.doctor", fake)
    assert client.get("/api/doctor").json() == [
        {"name": "python", "status": "ok", "detail": "3.13"}
    ]


def test_logs_tail(client: TestClient, isolated_home: Path) -> None:
    assert client.get("/api/logs").json() == {"lines": []}
    log_dir = isolated_home / "logs"
    log_dir.mkdir()
    (log_dir / "word-session.log").write_text(
        "\n".join(f"line {i}" for i in range(1, 11)) + "\n", encoding="utf-8"
    )
    assert client.get("/api/logs?tail=3").json()["lines"] == ["line 8", "line 9", "line 10"]
    assert len(client.get("/api/logs").json()["lines"]) == 10
    assert client.get("/api/logs?tail=1001").status_code == 422
    assert client.get("/api/logs?tail=0").status_code == 422


# ---- error mapping ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "status"),
    [(WordNotResponding("slow"), 504), (WordError("odd"), 502)],
)
def test_word_errors_map_to_status(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    service: SessionService,
    error: Exception,
    status: int,
) -> None:
    def fail() -> None:
        raise error

    monkeypatch.setattr(service, "word_info", fail)
    response = client.get("/api/word")
    assert response.status_code == status
    assert response.json()["error"]["type"] == type(error).__name__


def test_config_error_is_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, service: SessionService
) -> None:
    from word_session.config import ConfigError

    def fail(*args: object, **kwargs: object) -> None:
        raise ConfigError("bad config")

    monkeypatch.setattr("word_session.web.app.save_settings", fail)
    current = client.get("/api/settings").json()
    response = client.put("/api/settings", json=current)
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "bad config"


def test_unknown_api_path_is_json_404(client: TestClient) -> None:
    response = client.get("/api/nothing")
    assert response.status_code == 404


# ---- Start menu shortcut ----------------------------------------------------------


@pytest.fixture
def fake_link_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Write a stub file instead of running PowerShell, as if on Windows."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        shortcut, "_write_link", lambda link, target, arguments: link.write_bytes(b"lnk")
    )


def test_shortcut_create_and_remove(
    client: TestClient, isolated_home: Path, fake_link_writer: None
) -> None:
    link = isolated_home / "start-menu" / "Word Session.lnk"
    state = client.get("/api/shortcut").json()
    assert state == {"supported": True, "exists": False, "path": str(link)}
    assert client.put("/api/shortcut").json()["exists"] is True
    assert link.is_file()
    assert client.get("/api/shortcut").json()["exists"] is True
    assert client.delete("/api/shortcut").json()["exists"] is False
    assert not link.exists()


def test_shortcut_failure_is_500(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(link: Path, target: Path, arguments: str) -> None:
        raise shortcut.ShortcutError("could not create the shortcut: denied")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shortcut, "_write_link", fail)
    response = client.put("/api/shortcut")
    assert response.status_code == 500
    assert "denied" in response.json()["error"]["message"]


def test_shortcut_unsupported_off_windows(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert client.get("/api/shortcut").json()["supported"] is False
    assert client.put("/api/shortcut").status_code == 501


def test_shortcut_requires_login(anon_client: TestClient) -> None:
    assert anon_client.put("/api/shortcut").status_code == 401
