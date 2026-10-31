"""Tests for the ``open`` and ``app`` commands."""

import json
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any

import pytest

from word_session import __version__, cli
from word_session import app as app_module
from word_session.instance import InstanceInfo, write_instance
from word_session.service import SessionService
from word_session.web.server import start_server


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    urls: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda url: urls.append(url) or True)
    return urls


@pytest.fixture
def popen_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, dict[str, Any]]]:
    calls: list[tuple[Any, dict[str, Any]]] = []

    class FakePopen:
        def __init__(self, args: Any, **kwargs: Any) -> None:
            calls.append((args, kwargs))

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    return calls


def test_open_uses_running_instance(
    service: SessionService,
    isolated_home: Path,
    opened: list[str],
    popen_calls: list[Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    handle = start_server(service)
    try:
        info = InstanceInfo(
            pid=1, port=handle.port, secret=handle.auth.instance_secret, version=__version__
        )
        write_instance(isolated_home / "instance.json", info)
        assert cli.main(["open"]) == 0
    finally:
        handle.stop()
    assert len(opened) == 1
    assert opened[0].startswith(f"http://127.0.0.1:{handle.port}/login?code=")
    assert capsys.readouterr().out.strip() == opened[0]
    assert popen_calls == []


def test_open_starts_app_when_no_instance(
    isolated_home: Path,
    opened: list[str],
    popen_calls: list[tuple[Any, dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert cli.main(["--json", "open"]) == 0
    assert opened == []
    assert len(popen_calls) == 1
    command, kwargs = popen_calls[0]
    assert command.endswith("-m word_session app --open")
    assert kwargs["creationflags"] == (
        getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    )


def test_open_demo_passes_demo_to_the_app(
    opened: list[str], popen_calls: list[tuple[Any, dict[str, Any]]]
) -> None:
    assert cli.main(["--demo", "open"]) == 0
    assert popen_calls[0][0].endswith("-m word_session --demo app --open")


def test_open_with_stale_instance_file_starts_app(
    isolated_home: Path,
    opened: list[str],
    popen_calls: list[Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Nothing listens on the recorded port, so the instance file is stale.
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    write_instance(
        isolated_home / "instance.json",
        InstanceInfo(pid=1, port=port, secret="x", version="0"),
    )
    assert cli.main(["--json", "open"]) == 0
    assert json.loads(capsys.readouterr().out) == {"url": None, "started": True}
    assert len(popen_calls) == 1
    assert opened == []


def test_app_command_runs_app_with_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[tuple[bool, bool]] = []

    class FakeApp:
        def __init__(self, *, fake: bool = False, open_browser: bool = False) -> None:
            created.append((fake, open_browser))

        def run(self) -> int:
            return 0

    monkeypatch.setattr(app_module, "App", FakeApp)
    assert cli.main(["--demo", "app", "--open"]) == 0
    assert cli.main(["app"]) == 0
    assert created == [(True, True), (False, False)]


def test_app_main_runs_app_with_open(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(cli, "main", lambda argv: seen.append(argv) or 0)
    with pytest.raises(SystemExit) as exit_info:
        cli.app_main()
    assert exit_info.value.code == 0
    assert seen == [["app", "--open"]]


def test_shutdown_route_is_404_without_callback(service: SessionService) -> None:
    import httpx

    handle = start_server(service)
    try:
        reply = httpx.post(
            f"{handle.url}/api/internal/shutdown",
            headers={"X-Word-Session-Secret": handle.auth.instance_secret},
        )
    finally:
        handle.stop()
    assert reply.status_code == 404
