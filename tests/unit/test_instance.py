"""Tests for the single-instance lock, the instance file and the login-URL request."""

import os
import socket
import sys
import uuid
from pathlib import Path

import httpx
import pytest

from word_session import __version__
from word_session.instance import (
    InstanceInfo,
    InstanceLock,
    clear_instance,
    read_instance,
    request_login_url,
    write_instance,
)
from word_session.service import SessionService, open_service
from word_session.web.server import start_server


def _info(pid: int = 123) -> InstanceInfo:
    return InstanceInfo(pid=pid, port=4567, secret="s3cret", version="1.2.3")


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "state" / "instance.json"
    write_instance(path, _info())
    assert read_instance(path) == _info()
    assert [p.name for p in path.parent.iterdir()] == ["instance.json"]


def test_read_missing_or_invalid_is_none(tmp_path: Path) -> None:
    path = tmp_path / "instance.json"
    assert read_instance(path) is None
    path.write_text("{not json", encoding="utf-8")
    assert read_instance(path) is None
    path.write_text('{"pid": 1}', encoding="utf-8")
    assert read_instance(path) is None
    path.write_text("[1, 2]", encoding="utf-8")
    assert read_instance(path) is None


def test_clear_removes_only_our_file(tmp_path: Path) -> None:
    path = tmp_path / "instance.json"
    write_instance(path, _info(pid=10))
    clear_instance(path, 11)
    assert path.exists()
    clear_instance(path, 10)
    assert not path.exists()
    clear_instance(path, 10)  # a missing file is fine


def test_lock_second_acquire_fails_until_release(tmp_path: Path) -> None:
    path = tmp_path / "instance.lock"
    first = InstanceLock(path, use_mutex=False)
    second = InstanceLock(path, use_mutex=False)
    assert first.acquire()
    assert first.acquire()  # idempotent for the holder
    assert not second.acquire()
    first.release()
    assert not path.exists()
    assert second.acquire()
    second.release()
    second.release()  # harmless twice


@pytest.mark.parametrize("content", ["0", "not a pid", "", str(2**30)])
def test_lock_takes_over_stale_file(tmp_path: Path, content: str) -> None:
    path = tmp_path / "instance.lock"
    path.write_text(content, encoding="utf-8")
    lock = InstanceLock(path, use_mutex=False)
    assert lock.acquire()
    assert path.read_text(encoding="utf-8") == str(os.getpid())
    lock.release()


def test_lock_default_path_is_beside_instance_file(isolated_home: Path) -> None:
    lock = InstanceLock(use_mutex=False)
    assert lock.acquire()
    assert (isolated_home / "instance.lock").exists()
    lock.release()


def test_request_login_url_against_real_server() -> None:
    service = open_service(fake=True)
    try:
        handle = start_server(service)
        try:
            info = InstanceInfo(
                pid=os.getpid(),
                port=handle.port,
                secret=handle.auth.instance_secret,
                version=__version__,
            )
            url = request_login_url(info)
            assert url.startswith(f"http://127.0.0.1:{handle.port}/login?code=")
            with httpx.Client() as client:
                client.get(url, follow_redirects=True)
                reply = client.get(f"{handle.url}/api/sessions", headers={"X-Word-Session": "1"})
            assert reply.status_code == 200
        finally:
            handle.stop()
    finally:
        service.close()


def test_request_login_url_wrong_secret_raises(service: SessionService) -> None:
    handle = start_server(service)
    try:
        bad = InstanceInfo(pid=1, port=handle.port, secret="wrong", version="x")
        with pytest.raises(ConnectionError):
            request_login_url(bad)
    finally:
        handle.stop()


def test_request_login_url_nobody_listening_raises() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with pytest.raises(ConnectionError):
        request_login_url(InstanceInfo(pid=1, port=port, secret="x", version="x"), timeout=1)


@pytest.mark.skipif(sys.platform != "win32", reason="named mutexes exist on Windows only")
def test_named_mutex_lock_excludes_second_holder(tmp_path: Path) -> None:
    name = f"Local\\WordSession.Test.{os.getpid()}.{uuid.uuid4().hex}"
    first = InstanceLock(tmp_path / "unused.lock", use_mutex=True, mutex_name=name)
    second = InstanceLock(tmp_path / "unused.lock", use_mutex=True, mutex_name=name)
    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()
