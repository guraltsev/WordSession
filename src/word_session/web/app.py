"""ASGI application exposing the session service over a localhost-only HTTP API.

Call ``create_app(service, auth, port=...)`` to build the FastAPI application.
Every request passes the security checks (Host, Origin, session cookie and
custom header) before reaching a route; see ``docs/migration_plan.md`` section
3.8. Errors are reported as ``{"error": {"type": ..., "message": ...}}``.
"""

import dataclasses
import importlib
import importlib.resources
import logging
import secrets
from collections import deque
from collections.abc import Awaitable, Callable, MutableMapping
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

from word_session import __version__
from word_session.config import ConfigError, Settings, app_paths, save_settings
from word_session.legacy import ImportSummary
from word_session.model import DocumentState, Location, Session, SessionKind
from word_session.service import RestoreInProgress, RevisionConflict, SessionService
from word_session.store import AmbiguousSelector, SessionNotFound
from word_session.web.auth import Auth
from word_session.web.jobs import JobManager, JobNotFound, JobView
from word_session.web.sse import event_stream
from word_session.word.backend import (
    WordError,
    WordInfo,
    WordNotResponding,
    WordUnavailable,
)

_log = logging.getLogger(__name__)

__all__ = [
    "DocumentDetail",
    "JobView",
    "SessionDetail",
    "SessionSummary",
    "create_app",
]

_EXPIRED_PAGE = (
    "<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Link expired</title>"
    "</head><body><p>This link has expired. Open the manager again from the tray icon "
    "or run <code>word-session open</code>.</p></body></html>"
)


# ---- response and request models ------------------------------------------------


class SessionSummary(BaseModel):
    """One row of the session list."""

    id: str
    name: str
    kind: SessionKind
    pinned: bool
    created_at: datetime
    document_count: int
    missing_count: int  # local/unc documents whose file does not exist


class DocumentDetail(DocumentState):
    """A session document plus whether its file exists (None for url/unsaved)."""

    exists: bool | None = None


class SessionDetail(BaseModel):
    """A full session with its revision and per-document existence."""

    model_config = ConfigDict(extra="allow")

    format: str
    version: int
    id: str
    name: str
    kind: SessionKind
    pinned: bool
    created_at: datetime
    host: str
    word_version: str
    notes: str
    documents: list[DocumentDetail]
    revision: str


class CaptureBody(BaseModel):
    """Request body of ``POST /api/sessions``."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None


class CaptureResponse(BaseModel):
    """Response of ``POST /api/sessions``."""

    session: Session
    warnings: list[str]
    saved: bool


class PatchBody(BaseModel):
    """Request body of ``PATCH /api/sessions/{id}``; omitted fields stay unchanged."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    pinned: bool | None = None
    notes: str | None = None
    remove_paths: list[str] | None = None


class RestoreBody(BaseModel):
    """Request body of ``POST /api/sessions/{id}/restore``."""

    model_config = ConfigDict(extra="forbid")

    only: list[str] | None = None
    start_word: bool | None = None
    restore_position: bool | None = None
    dry_run: bool = False


class LogLines(BaseModel):
    """Response of ``GET /api/logs``."""

    lines: list[str] = Field(default_factory=list)


# ---- application factory --------------------------------------------------------


def create_app(
    service: SessionService,
    auth: Auth,
    *,
    port: int,
    job_manager: JobManager | None = None,
    on_shutdown: Callable[[], None] | None = None,
    on_settings_changed: Callable[[], None] | None = None,
) -> FastAPI:
    """Build the FastAPI application for one service.

    Parameters
    ----------
    service : SessionService
        Service the routes call.
    auth : Auth
        Login codes and session tokens.
    port : int
        Port the app is served on; Host/Origin checks and the cookie name
        (``ws_session_<port>``) depend on it.
    job_manager : JobManager | None
        Restore job runner; a new one is created when omitted.
    on_shutdown : Callable[[], None] | None
        Called by ``POST /api/internal/shutdown``; the route answers 404 when
        this is ``None``.
    on_settings_changed : Callable[[], None] | None
        Called after ``PUT /api/settings`` saved and applied new settings;
        defaults to doing nothing.

    Returns
    -------
    FastAPI
        The application, with security middleware, routes and static files.
    """
    jobs = job_manager if job_manager is not None else JobManager(service)
    cookie_name = f"ws_session_{port}"
    app = FastAPI(title="Word Session", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SecurityMiddleware, auth=auth, port=port, cookie_name=cookie_name)
    _register_error_handlers(app)

    def exact_session(session_id: str) -> Session:
        """Return the session whose id is exactly ``session_id``."""
        session = service.get(session_id)
        if session.id != session_id:
            raise SessionNotFound(f"no session with id {session_id!r}")
        return session

    def detail_of(session: Session) -> SessionDetail:
        """Build the detail view, checking each local file's existence."""
        data = session.model_dump(mode="json")
        for doc in data["documents"]:
            doc["exists"] = _exists(service, doc["path"], doc["location"])
        data["revision"] = service.revision(session.id)
        return SessionDetail.model_validate(data)

    # ---- unauthenticated pages ----

    @app.get("/login", include_in_schema=False)
    def login(code: str = "") -> Response:
        """Exchange a login code for a session cookie and redirect to the UI."""
        token = auth.exchange(code)
        if token is None:
            return HTMLResponse(_EXPIRED_PAGE, status_code=403)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(cookie_name, token, httponly=True, samesite="strict", path="/")
        return response

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        """Report that the server is up."""
        return {"ok": True, "version": __version__}

    @app.post("/api/internal/login-code")
    def login_code() -> dict[str, str]:
        """Mint a login code and the URL that redeems it."""
        code = auth.mint_login_code()
        return {"code": code, "url": f"http://127.0.0.1:{port}/login?code={code}"}

    @app.post("/api/internal/shutdown")
    def shutdown() -> dict[str, bool]:
        """Ask the application to quit (instance-secret protected)."""
        if on_shutdown is None:
            raise StarletteHTTPException(404, "not found")
        on_shutdown()
        return {"ok": True}

    # ---- Word ----

    @app.get("/api/word")
    def word() -> WordInfo:
        """Return facts about Word without starting it."""
        return service.word_info()

    @app.get("/api/word/documents")
    def word_documents() -> list[DocumentState]:
        """List the documents open in Word right now."""
        return service.current()

    # ---- sessions ----

    @app.get("/api/sessions")
    def list_sessions(
        kind: SessionKind | None = None, q: str | None = None, pinned: bool | None = None
    ) -> list[SessionSummary]:
        """List sessions, newest first, optionally filtered."""
        needle = q.casefold() if q else None
        summaries: list[SessionSummary] = []
        for session in service.list_sessions(kind=kind):
            # Apply the pinned and free-text filters.
            if pinned is not None and session.pinned != pinned:
                continue
            if needle is not None:
                haystack = [session.name, session.id, *(d.path for d in session.documents)]
                if not any(needle in text.casefold() for text in haystack):
                    continue
            missing = sum(
                1 for d in session.documents if _exists(service, d.path, d.location) is False
            )
            summaries.append(
                SessionSummary(
                    id=session.id,
                    name=session.name,
                    kind=session.kind,
                    pinned=session.pinned,
                    created_at=session.created_at,
                    document_count=len(session.documents),
                    missing_count=missing,
                )
            )
        return summaries

    @app.post("/api/sessions")
    def capture(response: Response, body: CaptureBody | None = None) -> CaptureResponse:
        """Save the documents open in Word as a new session."""
        result = service.capture(body.name if body is not None else None)
        saved = result.path is not None
        response.status_code = 201 if saved else 200
        return CaptureResponse(session=result.session, warnings=result.warnings, saved=saved)

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str, response: Response) -> SessionDetail:
        """Return one session with its ETag."""
        detail = detail_of(exact_session(session_id))
        response.headers["ETag"] = f'"{detail.revision}"'
        return detail

    @app.patch("/api/sessions/{session_id}")
    def patch_session(
        session_id: str,
        body: PatchBody,
        response: Response,
        if_match: str | None = Header(default=None),
    ) -> SessionDetail:
        """Change name, pinned flag, notes or documents of a session."""
        exact_session(session_id)
        revision = _require_if_match(if_match)
        updated = service.update(
            session_id,
            expected_revision=revision,
            name=body.name,
            pinned=body.pinned,
            notes=body.notes,
            remove_paths=body.remove_paths,
        )
        detail = detail_of(updated)
        response.headers["ETag"] = f'"{detail.revision}"'
        return detail

    @app.delete("/api/sessions/{session_id}", status_code=204)
    def delete_session(
        session_id: str, purge: bool = False, if_match: str | None = Header(default=None)
    ) -> Response:
        """Move a session to the trash, or delete it for good with ``purge``."""
        exact_session(session_id)
        revision = _require_if_match(if_match)
        # Same optimistic-concurrency check as PATCH, before anything is removed.
        if revision != service.revision(session_id):
            raise RevisionConflict(f"session {session_id} changed since it was read")
        service.delete(session_id, purge=purge)
        return Response(status_code=204)

    @app.post("/api/sessions/{session_id}/restore", status_code=202)
    def restore_session(session_id: str, body: RestoreBody | None = None) -> dict[str, str]:
        """Start a restore job and return its id."""
        exact_session(session_id)
        options = (body if body is not None else RestoreBody()).model_dump()
        return {"job_id": jobs.start_restore(session_id, **options)}

    # ---- jobs and events ----

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> JobView:
        """Return the state of a restore job."""
        return jobs.get(job_id)

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        """Stream service events as server-sent events."""
        return StreamingResponse(
            event_stream(service.events),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    # ---- settings, import, diagnostics ----

    @app.get("/api/settings")
    def get_settings() -> Settings:
        """Return the settings in effect."""
        return service.settings

    @app.put("/api/settings")
    def put_settings(settings: Settings) -> Settings:
        """Validate, save and apply new settings."""
        save_settings(settings)
        service.settings = settings
        if on_settings_changed is not None:
            on_settings_changed()
        return settings

    @app.post("/api/import-legacy")
    def import_legacy() -> ImportSummary:
        """Import sessions written by the old tools."""
        return service.import_legacy()

    @app.get("/api/doctor")
    def doctor() -> list[dict[str, Any]]:
        """Run the diagnostic checks."""
        # The doctor module arrives in a later job; until then there is nothing to run.
        try:
            module = importlib.import_module("word_session.doctor")
        except ModuleNotFoundError:
            return []
        checks = module.run_checks(service, app_paths())
        return [dataclasses.asdict(check) for check in checks]

    @app.get("/api/logs")
    def logs(tail: int = Query(default=200, ge=1, le=1000)) -> LogLines:
        """Return the last lines of the application log."""
        log_file = app_paths().log_dir / "word-session.log"
        try:
            text = log_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return LogLines()
        return LogLines(lines=list(deque(text.splitlines(), maxlen=tail)))

    # Static files go last so they never shadow a route.
    static_dir = Path(str(importlib.resources.files("word_session.web") / "static"))
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app


# ---- helpers --------------------------------------------------------------------


def _exists(service: SessionService, path: str, location: Location) -> bool | None:
    """Return whether a local or UNC file exists; None for url and unsaved documents."""
    if location not in ("local", "unc"):
        return None
    return service._path_exists(path)


def _require_if_match(header: str | None) -> str:
    """Extract the revision from an ``If-Match`` header or fail with 428."""
    if header is None:
        raise StarletteHTTPException(428, "If-Match header required")
    value = header.strip()
    if value.startswith("W/"):
        value = value[2:]
    return value.strip('"')


# ---- security middleware --------------------------------------------------------


class SecurityMiddleware:
    """Apply the Host, Origin, cookie and header checks and add security headers.

    Also turns unexpected exceptions into a JSON 500 so that even error
    responses carry the security headers.
    """

    def __init__(self, app: ASGIApp, *, auth: Auth, port: int, cookie_name: str) -> None:
        self.app = app
        self.auth = auth
        self.cookie_name = cookie_name
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Check the request, then run the app with security headers added."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope["path"]
        is_api = path.startswith("/api/")

        # Add the fixed headers to every response that starts.
        async def send_with_headers(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower()
                    not in (
                        b"content-security-policy",
                        b"x-content-type-options",
                        b"referrer-policy",
                    )
                ]
                headers += [
                    (b"content-security-policy", b"default-src 'self'"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                ]
                if is_api and not any(k.lower() == b"cache-control" for k, _ in headers):
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        # Reject requests that fail the checks before any route runs.
        rejection = self._check(scope, path, is_api)
        try:
            if rejection is not None:
                await rejection(scope, receive, send_with_headers)
                return
            await self.app(scope, receive, send_with_headers)
        except Exception as exc:
            _log.exception("unhandled error serving %s", path)
            response = _error_response(500, type(exc).__name__, "internal server error")
            await response(scope, receive, send_with_headers)

    def _check(self, scope: Scope, path: str, is_api: bool) -> JSONResponse | None:
        """Return an error response when the request violates a security rule."""
        request = Request(scope)
        headers = request.headers

        # DNS-rebinding defence: only our own host names are accepted.
        if headers.get("host", "").lower() not in self.hosts:
            return _error_response(400, "BadHost", "unexpected Host header")

        # Cross-site defence: a foreign Origin may not change state.
        origin = headers.get("origin")
        if (
            request.method not in ("GET", "HEAD")
            and origin is not None
            and origin.lower() not in self.origins
        ):
            return _error_response(403, "ForeignOrigin", "cross-origin request refused")

        # The login-code endpoint is guarded by the instance secret alone.
        if path.startswith("/api/internal/"):
            secret = headers.get("x-word-session-secret", "")
            if not _same(secret, self.auth.instance_secret):
                return _error_response(401, "Unauthorized", "missing or wrong secret")
            return None

        # Everything else under /api/ needs a login cookie and the custom header.
        if is_api and path != "/api/health":
            token = request.cookies.get(self.cookie_name)
            if not self.auth.is_valid_session(token) or headers.get("x-word-session") != "1":
                return _error_response(401, "Unauthorized", "login required")
        return None


def _same(a: str, b: str) -> bool:
    """Compare two strings in constant time."""
    return secrets.compare_digest(a.encode(), b.encode())


# ---- error mapping --------------------------------------------------------------


def _error_response(status: int, type_: str, message: str) -> JSONResponse:
    """Build the standard JSON error response."""
    return JSONResponse({"error": {"type": type_, "message": message}}, status_code=status)


def _register_error_handlers(app: FastAPI) -> None:
    """Map service and Word exceptions to HTTP status codes."""
    # Most specific classes first is not required: Starlette walks the MRO.
    mapping: list[tuple[type[Exception], int]] = [
        (SessionNotFound, 404),
        (JobNotFound, 404),
        (AmbiguousSelector, 409),
        (RevisionConflict, 412),
        (RestoreInProgress, 409),
        (WordUnavailable, 503),
        (WordNotResponding, 504),
        (WordError, 502),
        (ConfigError, 400),
    ]

    def make_handler(status: int) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
        async def handler(request: Request, exc: Exception) -> JSONResponse:
            message = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
            return _error_response(status, type(exc).__name__, message)

        return handler

    for exc_class, status in mapping:
        app.add_exception_handler(exc_class, make_handler(status))

    async def http_error(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, StarletteHTTPException)
        return _error_response(exc.status_code, "HTTPError", str(exc.detail))

    app.add_exception_handler(StarletteHTTPException, http_error)
