"""Tests for the ``quit-app`` command."""

import json
import socket
import types
from pathlib import Path

import pytest

from word_session import __version__, cli
from word_session.instance import InstanceInfo, write_instance
from word_session.service import SessionService
from word_session.web.server import start_server


def test_quit_app_without_instance_exits_zero(
    isolated_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--json", "quit-app"]) == 0
    assert json.loads(capsys.readouterr().out) == {"was_running": False}


def test_quit_app_with_stale_instance_file_exits_zero(
    isolated_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Nothing listens on the recorded port, so the instance file is stale.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    write_instance(
        isolated_home / "instance.json", InstanceInfo(pid=1, port=port, secret="x", version="0")
    )
    assert cli.main(["--json", "quit-app"]) == 0
    assert json.loads(capsys.readouterr().out) == {"was_running": False}


def test_quit_app_posts_shutdown_and_waits_for_the_instance_file(
    service: SessionService, isolated_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    instance_file = isolated_home / "instance.json"
    calls: list[str] = []

    def on_shutdown() -> None:
        # Like the real application: leave by removing the instance file.
        calls.append("shutdown")
        instance_file.unlink()

    handle = start_server(service, on_shutdown=on_shutdown)
    try:
        info = InstanceInfo(
            pid=1, port=handle.port, secret=handle.auth.instance_secret, version=__version__
        )
        write_instance(instance_file, info)
        assert cli.main(["--json", "quit-app"]) == 0
    finally:
        handle.stop()
    assert calls == ["shutdown"]
    assert json.loads(capsys.readouterr().out) == {"was_running": True}


def test_quit_app_fails_when_the_instance_keeps_running(
    service: SessionService,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The shutdown callback does nothing, so the instance file never disappears.
    # Replace only the command's clock (not the global one the server uses) so
    # the five seconds pass instantly.
    clock = iter(range(0, 1000, 3))
    fake_time = types.SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda seconds: None)
    monkeypatch.setattr(cli, "time", fake_time)
    handle = start_server(service, on_shutdown=lambda: None)
    try:
        info = InstanceInfo(
            pid=1, port=handle.port, secret=handle.auth.instance_secret, version=__version__
        )
        write_instance(isolated_home / "instance.json", info)
        assert cli.main(["quit-app"]) == 1
    finally:
        handle.stop()
    assert "did not stop" in capsys.readouterr().err
