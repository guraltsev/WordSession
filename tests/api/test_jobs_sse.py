"""Tests for restore jobs and the server-sent events stream."""

import asyncio
import json
import time
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from word_session.events import EventBus
from word_session.model import DocumentState, Session
from word_session.service import SessionService
from word_session.web.jobs import JobManager, JobNotFound, JobView
from word_session.web.server import start_server
from word_session.web.sse import event_stream
from word_session.word.fake import FakeWordBackend

A = "C:\\Docs\\a.docx"
C = "C:\\Docs\\c.docx"


def _store(service: SessionService, paths: list[str]) -> Session:
    created = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    docs = [DocumentState(path=p, location="local").model_dump(mode="json") for p in paths]
    session = Session.model_validate(
        {
            "id": service.store.new_id(created, "S"),
            "name": "S",
            "kind": "manual",
            "created_at": created,
            "documents": docs,
        }
    )
    service.store.save(session)
    return session


def _wait_for_job(manager: JobManager, job_id: str) -> JobView:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = manager.get(job_id)
        if job.state in ("done", "failed"):
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


# ---- jobs -------------------------------------------------------------------------


def test_restore_job_reaches_done_with_results(
    client: TestClient, service: SessionService, fake_backend: FakeWordBackend
) -> None:
    session = _store(service, [A, C])
    response = client.post(f"/api/sessions/{session.id}/restore", json={"restore_position": False})
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    # Poll the endpoint, as the browser does.
    deadline = time.monotonic() + 5
    body = {}
    while time.monotonic() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["state"] in ("done", "failed"):
            break
        time.sleep(0.01)
    assert body["state"] == "done"
    assert body["session_id"] == session.id
    assert [(r["path"], r["status"]) for r in body["results"]] == [
        (A, "already_open"),
        (C, "opened"),
    ]
    assert body["report"]["session_id"] == session.id
    assert body["error"] is None
    assert any(d.path == C for d in fake_backend.documents)


def test_dry_run_job_reports_without_word_calls(
    client: TestClient, service: SessionService, fake_backend: FakeWordBackend
) -> None:
    session = _store(service, [C])
    job_id = client.post(f"/api/sessions/{session.id}/restore", json={"dry_run": True}).json()[
        "job_id"
    ]
    deadline = time.monotonic() + 5
    while client.get(f"/api/jobs/{job_id}").json()["state"] not in ("done", "failed"):
        assert time.monotonic() < deadline
        time.sleep(0.01)
    body = client.get(f"/api/jobs/{job_id}").json()
    assert body["state"] == "done"
    assert body["report"]["dry_run"] is True
    assert all(d.path != C for d in fake_backend.documents)


def test_restore_in_progress_becomes_job_error(service: SessionService) -> None:
    session = _store(service, [A])
    manager = JobManager(service)
    # Pretend another restore holds the service.
    service._restoring = True
    try:
        job = _wait_for_job(manager, manager.start_restore(session.id))
    finally:
        service._restoring = False
    assert job.state == "failed"
    assert job.error is not None
    assert job.error.type == "RestoreInProgress"


def test_unknown_session_becomes_job_error(service: SessionService) -> None:
    manager = JobManager(service)
    job = _wait_for_job(manager, manager.start_restore("nope"))
    assert job.state == "failed"
    assert job.error is not None
    assert job.error.type == "SessionNotFound"


def test_job_manager_keeps_only_recent_jobs(service: SessionService) -> None:
    session = _store(service, [A])
    manager = JobManager(service, keep=2)
    ids = [manager.start_restore(session.id, dry_run=True) for _ in range(4)]
    for job_id in ids[-2:]:
        _wait_for_job(manager, job_id)
    with pytest.raises(JobNotFound):
        manager.get(ids[0])
    assert manager.get(ids[-1]).id == ids[-1]


def test_job_not_found_is_a_key_error(service: SessionService) -> None:
    with pytest.raises(KeyError):
        JobManager(service).get("missing")


# ---- SSE generator -------------------------------------------------------------


def test_event_stream_hello_events_and_unsubscribe() -> None:
    async def scenario() -> None:
        bus = EventBus()
        stream = event_stream(bus)
        assert await anext(stream) == "event: hello\ndata: {}\n\n"
        bus.publish({"type": "session_saved", "session_id": "x"})
        frame = await anext(stream)
        assert frame.startswith("event: session_saved\ndata: ")
        assert json.loads(frame.split("data: ")[1]) == {"type": "session_saved", "session_id": "x"}
        await stream.aclose()
        # Publishing after the client left must not fail.
        bus.publish({"type": "late"})

    asyncio.run(scenario())


def test_event_stream_keepalive_when_idle() -> None:
    async def scenario() -> None:
        stream = event_stream(EventBus(), keepalive=0.01)
        await anext(stream)
        assert await anext(stream) == ": keepalive\n\n"
        await stream.aclose()

    asyncio.run(scenario())


def test_event_stream_bridges_threads_and_serves_every_client() -> None:
    async def scenario() -> None:
        bus = EventBus()
        first, second = event_stream(bus), event_stream(bus)
        await anext(first)
        await anext(second)
        await asyncio.to_thread(bus.publish, {"type": "ping"})
        assert "event: ping" in await anext(first)
        assert "event: ping" in await anext(second)
        await first.aclose()
        await second.aclose()

    asyncio.run(scenario())


# ---- SSE over real HTTP ----------------------------------------------------------


def test_sse_over_http_yields_hello_then_session_saved(service: SessionService) -> None:
    # TestClient buffers whole responses, so the endless stream is read over a real socket.
    handle = start_server(service)
    try:
        code = handle.auth.mint_login_code()
        with httpx.Client(base_url=handle.url, timeout=5) as http:
            assert http.get(f"/login?code={code}", follow_redirects=False).status_code == 303
            headers = {"X-Word-Session": "1"}
            with http.stream("GET", "/api/events", headers=headers) as stream:
                assert stream.status_code == 200
                assert stream.headers["content-type"].startswith("text/event-stream")
                lines = stream.iter_lines()
                seen: list[str] = []
                for line in lines:
                    if line.startswith("event:"):
                        seen.append(line)
                        break
                assert seen == ["event: hello"]
                # A capture made through the API announces itself on the stream.
                post = http.post("/api/sessions", json={"name": "Live"}, headers=headers)
                assert post.status_code == 201
                for line in lines:
                    if line.startswith("event:"):
                        seen.append(line)
                        break
                assert seen == ["event: hello", "event: session_saved"]
    finally:
        handle.stop()
