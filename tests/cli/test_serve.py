"""Tests for the ``serve`` command."""

import threading
import webbrowser
from typing import Any

import httpx
import pytest

from word_session import cli
from word_session.web import server
from word_session.web.server import ServerHandle


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Wrap ``start_server`` to record its handle; record browser opens."""
    info: dict[str, Any] = {"ready": threading.Event(), "opened": []}
    real_start = server.start_server

    def wrapped(*args: Any, **kwargs: Any) -> ServerHandle:
        handle = real_start(*args, **kwargs)
        info["handle"] = handle
        info["ready"].set()
        return handle

    monkeypatch.setattr(server, "start_server", wrapped)
    monkeypatch.setattr(webbrowser, "open", lambda url: info["opened"].append(url) or True)
    return info


def _run_serve(argv: list[str], captured: dict[str, Any]) -> tuple[threading.Thread, list[int]]:
    """Run ``main(argv)`` in a thread and return it with its exit-code list."""
    codes: list[int] = []
    thread = threading.Thread(target=lambda: codes.append(cli.main(argv)), daemon=True)
    thread.start()
    assert captured["ready"].wait(10), "server did not start"
    return thread, codes


def test_serve_runs_and_stops(captured: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    thread, codes = _run_serve(["--demo", "serve", "--port", "0"], captured)
    handle: ServerHandle = captured["handle"]

    # The server answers while the command blocks.
    assert httpx.get(f"{handle.url}/api/health").json()["ok"] is True
    assert thread.is_alive()

    # Setting the stop event ends the command with exit code 0.
    cli.serve_stop.set()
    thread.join(10)
    assert not thread.is_alive()
    assert codes == [0]
    out = capsys.readouterr().out
    assert "Word Session manager: http://127.0.0.1:" in out
    assert "/login?code=" in out
    assert "Press Ctrl+C to stop" in out
    assert captured["opened"] == []


def test_serve_open_launches_browser_with_login_url(captured: dict[str, Any]) -> None:
    thread, codes = _run_serve(["--demo", "serve", "--open", "--no-import"], captured)
    handle: ServerHandle = captured["handle"]
    cli.serve_stop.set()
    thread.join(10)
    assert codes == [0]
    assert len(captured["opened"]) == 1
    assert captured["opened"][0].startswith(f"{handle.url}/login?code=")


def test_serve_login_url_signs_in(
    captured: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    thread, _ = _run_serve(["--demo", "serve"], captured)
    handle: ServerHandle = captured["handle"]
    url = next(
        line.split(": ", 1)[1]
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("Word Session manager: ")
    )
    with httpx.Client() as client:
        client.get(url, follow_redirects=True)
        sessions = client.get(f"{handle.url}/api/sessions", headers={"X-Word-Session": "1"})
    assert sessions.status_code == 200
    cli.serve_stop.set()
    thread.join(10)


def test_serve_ends_on_keyboard_interrupt(
    captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    class InterruptingEvent(threading.Event):
        def wait(self, timeout: float | None = None) -> bool:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli, "serve_stop", InterruptingEvent())
    assert cli.main(["--demo", "serve", "--no-import"]) == 0
