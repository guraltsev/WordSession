"""Tests for ``start_server``: real HTTP on a free localhost port."""

import socket

import httpx

from word_session import __version__
from word_session.service import SessionService
from word_session.web.server import start_server


def test_start_server_serves_health_and_stop_frees_port(service: SessionService) -> None:
    handle = start_server(service, port=0)
    try:
        assert handle.port > 0
        assert handle.url == f"http://127.0.0.1:{handle.port}"
        response = httpx.get(f"{handle.url}/api/health", timeout=5)
        assert response.status_code == 200
        assert response.json() == {"ok": True, "version": __version__}
        # The API is protected over real HTTP too.
        assert httpx.get(f"{handle.url}/api/word", timeout=5).status_code == 401
    finally:
        handle.stop()

    # The port can be bound again once the server has stopped.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", handle.port))


def test_login_flow_over_real_http(service: SessionService) -> None:
    handle = start_server(service)
    try:
        minted = httpx.post(
            f"{handle.url}/api/internal/login-code",
            headers={"X-Word-Session-Secret": handle.auth.instance_secret},
            timeout=5,
        ).json()
        with httpx.Client(timeout=5) as http:
            response = http.get(minted["url"], follow_redirects=False)
            assert response.status_code == 303
            word = http.get(f"{handle.url}/api/word", headers={"X-Word-Session": "1"})
            assert word.status_code == 200
    finally:
        handle.stop()
