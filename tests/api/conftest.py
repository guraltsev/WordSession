"""Fixtures for the HTTP API tests."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from word_session.service import SessionService
from word_session.web.app import create_app
from word_session.web.auth import Auth

PORT = 8765
BASE_URL = f"http://127.0.0.1:{PORT}"


@pytest.fixture
def auth() -> Auth:
    """Return a fresh ``Auth``."""
    return Auth()


@pytest.fixture
def app(service: SessionService, auth: Auth) -> FastAPI:
    """Return the application over the fake-Word service."""
    return create_app(service, auth, port=PORT)


@pytest.fixture
def anon_client(app: FastAPI) -> Iterator[TestClient]:
    """Return a client that has not logged in."""
    with TestClient(app, base_url=BASE_URL) as c:
        yield c


@pytest.fixture
def client(app: FastAPI, auth: Auth) -> Iterator[TestClient]:
    """Return a logged-in client that sends the ``X-Word-Session`` header."""
    with TestClient(app, base_url=BASE_URL) as c:
        response = c.get(f"/login?code={auth.mint_login_code()}", follow_redirects=False)
        assert response.status_code == 303
        c.headers["X-Word-Session"] = "1"
        yield c
