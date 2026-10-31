"""Security tests: Host, Origin, cookie, header, login codes and response headers."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.api.conftest import BASE_URL, PORT
from word_session.service import SessionService
from word_session.web.app import create_app
from word_session.web.auth import Auth


def test_wrong_host_is_rejected(client: TestClient) -> None:
    assert client.get("/api/health", headers={"Host": "evil.example:8765"}).status_code == 400
    assert client.get("/api/health", headers={"Host": "127.0.0.1:1"}).status_code == 400


def test_localhost_host_is_accepted(client: TestClient) -> None:
    assert client.get("/api/health", headers={"Host": f"localhost:{PORT}"}).status_code == 200


def test_foreign_origin_on_post_is_rejected(client: TestClient) -> None:
    response = client.post("/api/sessions", headers={"Origin": "http://evil.example"})
    assert response.status_code == 403
    assert response.json()["error"]["type"] == "ForeignOrigin"


def test_own_origin_on_post_is_accepted(client: TestClient) -> None:
    response = client.post("/api/sessions", headers={"Origin": BASE_URL})
    assert response.status_code == 201


def test_foreign_origin_on_get_is_not_checked(client: TestClient) -> None:
    assert client.get("/api/health", headers={"Origin": "http://evil.example"}).status_code == 200


def test_missing_custom_header_is_unauthorized(client: TestClient) -> None:
    response = client.get("/api/word", headers={"X-Word-Session": ""})
    assert response.status_code == 401
    assert response.json()["error"]["type"] == "Unauthorized"


def test_missing_cookie_is_unauthorized(anon_client: TestClient) -> None:
    response = anon_client.get("/api/word", headers={"X-Word-Session": "1"})
    assert response.status_code == 401


def test_invalid_cookie_is_unauthorized(anon_client: TestClient) -> None:
    anon_client.cookies.set(f"ws_session_{PORT}", "forged")
    assert anon_client.get("/api/word", headers={"X-Word-Session": "1"}).status_code == 401


def test_health_needs_no_login(anon_client: TestClient) -> None:
    body = anon_client.get("/api/health").json()
    assert body["ok"] is True
    assert "version" in body


def test_static_files_need_no_login(anon_client: TestClient) -> None:
    response = anon_client.get("/")
    assert response.status_code == 200
    assert "job 16" in response.text


def test_login_sets_strict_httponly_cookie(app: FastAPI, auth: Auth) -> None:
    with TestClient(app, base_url=BASE_URL) as c:
        response = c.get(f"/login?code={auth.mint_login_code()}", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        cookie = response.headers["set-cookie"].lower()
        assert f"ws_session_{PORT}=" in cookie
        assert "httponly" in cookie
        assert "samesite=strict" in cookie
        assert "path=/" in cookie


def test_invalid_code_shows_expired_page(anon_client: TestClient) -> None:
    response = anon_client.get("/login?code=nope", follow_redirects=False)
    assert response.status_code == 403
    assert "This link has expired" in response.text
    assert "word-session open" in response.text


def test_expired_code_is_rejected(service: SessionService) -> None:
    now = [0.0]
    auth = Auth(code_ttl=60, clock=lambda: now[0])
    app = create_app(service, auth, port=PORT)
    code = auth.mint_login_code()
    now[0] = 61.0
    with TestClient(app, base_url=BASE_URL) as c:
        assert c.get(f"/login?code={code}", follow_redirects=False).status_code == 403


def test_code_is_single_use(app: FastAPI, auth: Auth) -> None:
    code = auth.mint_login_code()
    with TestClient(app, base_url=BASE_URL) as c:
        assert c.get(f"/login?code={code}", follow_redirects=False).status_code == 303
    with TestClient(app, base_url=BASE_URL) as c:
        assert c.get(f"/login?code={code}", follow_redirects=False).status_code == 403


def test_two_logins_both_stay_valid(app: FastAPI, auth: Auth) -> None:
    with (
        TestClient(app, base_url=BASE_URL) as first,
        TestClient(app, base_url=BASE_URL) as second,
    ):
        for c in (first, second):
            c.get(f"/login?code={auth.mint_login_code()}", follow_redirects=False)
            c.headers["X-Word-Session"] = "1"
        assert first.get("/api/word").status_code == 200
        assert second.get("/api/word").status_code == 200
        assert first.get("/api/word").status_code == 200


def test_internal_login_code_requires_secret(anon_client: TestClient) -> None:
    assert anon_client.post("/api/internal/login-code").status_code == 401
    wrong = anon_client.post("/api/internal/login-code", headers={"X-Word-Session-Secret": "x"})
    assert wrong.status_code == 401


def test_internal_login_code_round_trip(anon_client: TestClient, auth: Auth) -> None:
    response = anon_client.post(
        "/api/internal/login-code", headers={"X-Word-Session-Secret": auth.instance_secret}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["url"] == f"http://127.0.0.1:{PORT}/login?code={body['code']}"
    assert auth.exchange(body["code"]) is not None


@pytest.mark.parametrize("path", ["/", "/api/health", "/login?code=x", "/api/word"])
def test_security_headers_everywhere(client: TestClient, path: str) -> None:
    response = client.get(path, follow_redirects=False)
    assert response.headers["content-security-policy"] == "default-src 'self'"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_api_responses_are_not_cached(client: TestClient) -> None:
    assert client.get("/api/word").headers["cache-control"] == "no-store"
    assert client.get("/api/health").headers["cache-control"] == "no-store"


def test_rejections_carry_security_headers(anon_client: TestClient) -> None:
    response = anon_client.get("/api/word")
    assert response.status_code == 401
    assert response.headers["x-content-type-options"] == "nosniff"


def test_no_cors_headers(client: TestClient) -> None:
    response = client.get("/api/word", headers={"Origin": BASE_URL})
    assert not [h for h in response.headers if h.lower().startswith("access-control-")]
    preflight = client.options(
        "/api/sessions",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert not [h for h in preflight.headers if h.lower().startswith("access-control-")]


def test_unexpected_error_is_json_500(
    service: SessionService, auth: Auth, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(service, auth, port=PORT)

    def boom() -> None:
        raise ZeroDivisionError("boom")

    monkeypatch.setattr(service, "word_info", boom)
    with TestClient(app, base_url=BASE_URL) as c:
        c.get(f"/login?code={auth.mint_login_code()}", follow_redirects=False)
        c.headers["X-Word-Session"] = "1"
        response = c.get("/api/word")
    assert response.status_code == 500
    assert response.json()["error"]["type"] == "ZeroDivisionError"
    assert response.headers["x-content-type-options"] == "nosniff"
