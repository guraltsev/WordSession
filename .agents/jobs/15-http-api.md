# Job 15 — Local HTTP API

Depends on: 11
Plan reference: §3.8 (security, endpoints), §3.9 (multiple tabs)
Decisions: D2 (FastAPI + uvicorn)

## Goal

Expose the service over a localhost-only HTTP API that the browser UI, the
tray and a second app launch can use, safe against other web pages running
in the same browser.

## Files

- `pyproject.toml` (add runtime deps `fastapi>=0.115`, `uvicorn>=0.30`; dev
  dep `httpx>=0.27`)
- `src/word_session/web/__init__.py`, `app.py`, `auth.py`, `jobs.py`,
  `sse.py`, `server.py`
- `src/word_session/web/static/index.html` (placeholder: "UI arrives in job 16")
- `tests/api/__init__.py`, `tests/api/conftest.py`, `tests/api/test_security.py`,
  `tests/api/test_endpoints.py`, `tests/api/test_jobs_sse.py`,
  `tests/api/test_server.py`

## Contract — `auth.py`

```python
class Auth:
    def __init__(self, *, code_ttl: float = 60.0,
                 clock: Callable[[], float] = time.monotonic) -> None: ...
    instance_secret: str                      # secrets.token_urlsafe(32)
    def mint_login_code(self) -> str: ...     # single use, expires after code_ttl
    def exchange(self, code: str) -> str | None: ...   # → new session token or None
    def is_valid_session(self, token: str | None) -> bool: ...
```

Session tokens never expire while the process runs; many may be valid at
once (one per tab login). Use `secrets.compare_digest` for comparisons.

## Contract — `app.py`

```python
def create_app(service: SessionService, auth: Auth, *, port: int,
               job_manager: JobManager | None = None) -> FastAPI: ...
```

Security, applied by middleware to every request:

1. `Host` header must be `127.0.0.1:<port>` or `localhost:<port>` → else
   `400`.
2. For methods other than GET/HEAD: if `Origin` is present it must be
   `http://127.0.0.1:<port>` or `http://localhost:<port>` → else `403`.
3. Paths under `/api/` except `/api/health` and `/api/internal/…` require
   cookie `ws_session_<port>` valid per `auth.is_valid_session` **and**
   header `X-Word-Session: 1` → else `401` JSON error.
4. `/api/internal/login-code` (POST) requires header
   `X-Word-Session-Secret` equal to `auth.instance_secret` → else `401`.
5. Response headers everywhere: `Content-Security-Policy: default-src 'self'`,
   `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`; API
   responses also `Cache-Control: no-store`. Never send CORS headers.

Routes:

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/login?code=` | valid → set cookie (`HttpOnly`, `SameSite=Strict`, `Path=/`), `303` to `/`; invalid/expired → `403` small HTML page: "This link has expired. Open the manager again from the tray icon or run `word-session open`." |
| GET | `/` and static files | from `web/static` (via `importlib.resources`), no auth (no data in them) |
| GET | `/api/health` | `{"ok": true, "version": __version__}` |
| POST | `/api/internal/login-code` | `{"code": ..., "url": "http://127.0.0.1:<port>/login?code=..."}` |
| GET | `/api/word` | `WordInfo` |
| GET | `/api/word/documents` | `[DocumentState]` |
| GET | `/api/sessions?kind=&q=&pinned=` | `[SessionSummary]`; `q` filters name/id/paths case-insensitively |
| POST | `/api/sessions` | body `{"name": str|null}` → `{"session", "warnings", "saved": bool}`; `201` if saved, `200` if not |
| GET | `/api/sessions/{id}` | `SessionDetail`; header `ETag: "<revision>"` |
| PATCH | `/api/sessions/{id}` | body `{"name"?, "pinned"?, "notes"?, "remove_paths"?}`; requires `If-Match` (`428` if absent, `412` on mismatch); returns `SessionDetail` + new `ETag` |
| DELETE | `/api/sessions/{id}?purge=false` | requires `If-Match` like PATCH; `204` |
| POST | `/api/sessions/{id}/restore` | body `{"only"?, "start_word"?, "restore_position"?, "dry_run"?}` → `202 {"job_id"}` |
| GET | `/api/jobs/{job_id}` | `JobView` |
| GET | `/api/events` | SSE stream (see below) |
| GET/PUT | `/api/settings` | `Settings`; PUT validates, `save_settings`, replaces `service.settings` |
| POST | `/api/import-legacy` | `ImportSummary` as JSON |
| GET | `/api/doctor` | `[Check]` |
| GET | `/api/logs?tail=200` | `{"lines": [...]}`; `tail` ≤ 1000 |

Response models (pydantic, in `app.py`):

- `SessionSummary`: `id, name, kind, pinned, created_at, document_count, missing_count`
  (`missing_count` uses `service`'s `path_exists` for local/unc docs).
- `SessionDetail`: the `Session` fields plus `revision` and, per document,
  `exists: bool | None` (`None` for url/unsaved).
- `JobView`: `id, state ("queued"|"running"|"done"|"failed"), session_id,
  results: [RestoreResult], report: RestoreReport | None, error: {"type","message"} | None`.

Error mapping (JSON body `{"error": {"type", "message"}}`): `SessionNotFound`
404, `AmbiguousSelector` 409, `RevisionConflict` 412, `RestoreInProgress`
409, `WordUnavailable` 503, `WordNotResponding` 504, other `WordError` 502,
`ConfigError` 400, unexpected 500 (logged with traceback).

The session id in paths is passed to the service as a selector but must be
an exact id: return 404 if `service.get(id).id != id`.

## Contract — `jobs.py`

```python
class JobManager:
    def __init__(self, service: SessionService, *, keep: int = 50) -> None: ...
    def start_restore(self, session_id: str, **options) -> str: ...   # job id
    def get(self, job_id: str) -> JobView: ...                        # KeyError → 404
```

Runs each restore on its own `threading.Thread` (the service serialises
Word access and raises `RestoreInProgress`; that becomes the job's error).
Collects results via the `progress` callback. Keeps the last `keep` jobs.

## Contract — `sse.py`

An async generator bound to the `EventBus`: on connect yield
`event: hello`; each bus event as `event: <type>\ndata: <json>\n\n`; a
`: keepalive` comment every 15 s; unsubscribes on disconnect. Bridge thread →
loop with `loop.call_soon_threadsafe(queue.put_nowait, event)`. Every
connected client receives every event (multiple tabs are first-class).

## Contract — `server.py`

```python
@dataclass
class ServerHandle:
    port: int
    url: str                  # "http://127.0.0.1:<port>"
    auth: Auth
    def stop(self, timeout: float = 5.0) -> None: ...

def start_server(service: SessionService, *, port: int = 0) -> ServerHandle: ...
```

Bind a socket to `("127.0.0.1", port)` first (so the real port is known
before `create_app`), then run `uvicorn.Server(uvicorn.Config(app,
log_config=None, access_log=False))` in a daemon thread named
`"http-server"` with `server.run(sockets=[sock])`; wait up to 10 s for
`server.started`. `stop` sets `should_exit` and joins.

## Tests

- `conftest.py`: `app` built with the job 11 `service` fixture and
  `port=8765`; `client` = `TestClient(app, base_url="http://127.0.0.1:8765")`
  logged in (mint code → GET `/login` → cookie kept) with default header
  `X-Word-Session: 1`; `anon_client` without login.
- security: wrong Host, foreign Origin on POST, missing header, missing or
  invalid cookie, expired code (inject clock), code single use, two logins
  both stay valid, internal endpoint secret, security headers present, no
  `Access-Control-*` headers.
- endpoints: each route's happy path and its error mappings; ETag/If-Match
  428/412 flow; `q` filter; settings round-trip and invalid PUT 422.
- jobs/SSE: restore job reaches `done` with results; `RestoreInProgress`
  as job error; SSE stream yields `hello` then a `session_saved` after a
  POST (read with `client.stream`, with a timeout).
- server: `start_server(port=0)` → real HTTP GET `/api/health` with `httpx`
  → 200; `stop()` frees the port.

## Acceptance

README rule 7 commands; `git grep -n -E "import (fastapi|uvicorn|starlette)" src/ | grep -v "src/word_session/web/"` prints nothing.
