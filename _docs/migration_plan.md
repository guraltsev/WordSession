# Word Session — Migration Plan

Goal: turn the current collection of scripts into one solid, testable,
resilient Windows tool for saving and restoring Microsoft Word sessions, with
three front ends over a single core:

- a **CLI** (`word-session ...`) for scripting and power use,
- a **system-tray app** for one-click save/restore and background autosave,
- a **visual manager** (HTML UI served by a small local HTTP server and
  opened in the user's default browser; no embedded window toolkit).

Status: proposal, 2026-10-31.

---

## 1. Current state

### 1.1 Inventory

| Path | What it is | State |
| --- | --- | --- |
| `word_session_lib.py` | COM helpers: list docs, go to page/line, get Word | Works, with defects (§1.2) |
| `word-session.py` | argparse CLI: `save` / `load` | **Does not compile** (`else` without `:` at line 119) |
| `word-session-examples.py` | `# %%` cells exercising the lib | Scratch |
| `word-session-gui.py` | wxPython list-with-checkboxes prototype | Dummy data, not wired to anything |
| `word-session.ps1` + 3 `.cmd` | Older PowerShell implementation | Separate file format and directory |
| `new/` | Byte-identical copy of the root Python files | Same syntax error |
| `new/distrib/` | Fixed CLI (syntax fix, empty-dir guard, nicer output) + PyInstaller spec | **The only working Python version** — treat as canonical |
| `requirements.txt` (×3) | `pywin32==308` | UTF-16 LE with BOM; fights `.gitattributes` (`*.txt eol=lf`) |
| `venv/` | Python 3.13.0 venv with pywin32, wxPython, ipykernel | **Broken**: base interpreter `C:\opt\Python\current\App` no longer exists |
| `_docs/` | `python_rules.md`, `docstring_schema.md`, empty `development_guide.md` | `AGENTS.md` points to `docs/…` and to a `docs/tests.md` that does not exist |
| git | Repo initialised, **no commits**, branch `master` (main branch is meant to be `main`) | Nothing is under version control yet |

### 1.2 Defects and risks found

Functional bugs

1. **CLI crashes on start** (root and `new/`): syntax error. Only
   `new/distrib/word-session.py` runs.
2. **Capture mutates the user's Word state**: `get_current_word_documents`
   calls `doc.Activate()` on every document, so after a save the active
   window is whatever document was last in the collection, and windows flash.
3. **`get_word_com(start_if_not_running=False)` ignores its own probe**: it
   calls `GetActiveObject` only for the exception, discards the result, then
   calls `EnsureDispatch`, which can start Word anyway in a race. The
   docstring says it returns `None` when Word is absent; it actually raises.
4. **Restore aborts on the first bad document**: one missing/moved/locked file
   raises out of the loop and the remaining documents are never opened.
5. **Restore can hang forever**: `Documents.Open` may raise a modal dialog
   (file in use, repair, conversion, macro warning, protected view). The
   COM call blocks the script indefinitely. `DisplayAlerts` is never set.
6. **Unsaved documents are recorded as unopenable paths** ("Document1").
7. **Cloud documents** (OneDrive/SharePoint) have `FullName` = `https://…`;
   any future `os.path.exists` check would wrongly flag them as missing.
8. **Position model is fragile**: page + line-on-page shifts with any layout
   change (printer, fonts, edits, view mode; page number is `-1` in some
   views). No character offset is stored.
9. **"Latest session"** is chosen by `getctime` over *every* file in the
   directory (non-JSON files included).
10. **PowerShell `LoadSession` goes to the wrong line**: it stores the line
    *within the page* but calls `GoTo(wdGoToLine, wdGoToAbsolute, line)`,
    i.e. absolute line in the document, and ignores the page.
11. **PowerShell `GetDocuments`** (the default action and the target of
    `word-session-GetDocuments.cmd`) matches no branch and does nothing.
12. **PowerShell `LoadSession` always starts a new Word instance**
    (`New-Object -ComObject`) instead of reusing the running one.

Robustness / maintainability

13. `gencache.EnsureDispatch` + `win32com.client.constants`: depends on the
    generated `gen_py` cache, a well-known source of
    `AttributeError: … CLSIDToClassMap` corruption, and awkward inside a
    PyInstaller bundle. The handful of constants used can be hard-coded and
    late binding (`dynamic.Dispatch`) used instead.
14. No handling of `RPC_E_CALL_REJECTED` / `RPC_E_SERVERCALL_RETRYLATER`
    (Word busy, user typing, dialog open) — these are routine, not exceptional.
15. Output via `print`, no logging, no exit codes (`main()` return value is
    never passed to `sys.exit`), `override_args` `NameError` hack for
    interactive use.
16. JSON written non-atomically, without explicit encoding; a crash mid-write
    leaves a truncated session file.
17. Hyphenated module names (`word-session.py`) are not importable, so nothing
    is unit-testable; there are no tests at all.

Data-format fragmentation (must be handled by the importer)

| Source | Directory | Top-level key | Fields | Encoding |
| --- | --- | --- | --- | --- |
| Python v0 | `~/.word-session/` | `"word-session:"` (trailing colon) | `FullName`, `Line`, `Page` | cp1252/ASCII |
| PowerShell | `~/.word-sessions/` | `"sessions"` | `FullName`, `cursorLine`, `pageNumber` | **UTF-16 LE** (PS 5.1 `Out-File` default) |

---

## 2. Goals and non-goals

Goals

- One importable package; every front end is a thin layer over the same
  service API.
- Core logic testable without Word (fake backend), plus an opt-in
  integration suite that drives real Word.
- Never lose a session file; never leave the user's Word in a surprising
  state; never hang a front end on a stuck COM call.
- Per-document results on restore (opened / already open / missing / failed /
  skipped) instead of all-or-nothing.
- Read every legacy session file ever written.
- Ship as a per-user Windows install that needs no Python.

Non-goals (for now)

- Non-Windows platforms (Word COM is Windows-only; the core stays portable,
  but no macOS backend).
- Multiple simultaneous Word instances (only the one in the Running Object
  Table is reachable; documented limitation).
- A Word add-in (VSTO/Office.js). Out-of-process COM is sufficient.

---

## 3. Target architecture

### 3.1 Layers

```
            ┌──────────┐   ┌────────────────┐   ┌────────────────────┐
front ends  │   CLI    │   │ Tray (pystray) │   │ Default browser tab│
            └────┬─────┘   └──────┬─────────┘   └──────────┬─────────┘
                 │                │  in-process          │ HTTP + token
                 │                ▼                      ▼
                 │         ┌─────────────────────────────────────┐
                 │         │ web: local HTTP API + static UI     │
                 │         └──────────────────┬──────────────────┘
                 ▼                            ▼
            ┌───────────────────────────────────────────────────┐
service     │ SessionService: capture, restore(+report), list,  │
            │ rename, delete, pin, prune, import_legacy, autosave│
            └──────────┬───────────────────────────┬────────────┘
                       ▼                           ▼
            ┌────────────────────┐      ┌─────────────────────────┐
adapters    │ SessionStore (files)│      │ WordBackend (Protocol)  │
            │ atomic, versioned,  │      │  ├ ComWordBackend        │
            │ legacy readers      │      │  │  via ComWorker (STA)  │
            └────────────────────┘      │  └ FakeWordBackend       │
                                        └─────────────────────────┘
model       Session, DocumentState, RestoreReport (pure, no I/O)
```

Rule: only `word/com.py` imports `pywin32`; only `web/` imports the web
framework; only `tray.py` imports `pystray`. Everything else is plain Python
and runs on any OS in CI.

### 3.2 Repository layout

```
pyproject.toml              # uv-managed; entry points below
uv.lock
src/word_session/
    __init__.py             # version
    __main__.py             # python -m word_session
    model.py                # Session, DocumentState, RestoreResult/Report
    store.py                # SessionStore: list/load/save/delete/rename/prune
    legacy.py               # readers for Python-v0 and PowerShell files
    config.py               # Settings (TOML) + platform paths
    service.py              # SessionService (use cases)
    logging_setup.py        # rotating file log + console handler
    word/
        backend.py          # WordBackend Protocol, errors
        com.py              # ComWordBackend (pywin32, late binding)
        worker.py           # ComWorker: single STA thread, timeouts, retry
        fake.py             # FakeWordBackend for tests and demo mode
        constants.py        # hard-coded Wd* constants
    cli.py                  # argparse subcommands
    web/
        app.py              # HTTP API + static file serving
        auth.py             # one-time login codes, session cookie, Host checks
        static/             # index.html, app.js, app.css (no build step)
    tray.py                 # pystray icon + menu
    instance.py             # single-instance mutex + instance.json
    autostart.py            # HKCU\...\Run toggle
tests/
    unit/  contract/  cli/  api/  ui/  integration/   fixtures/legacy/
packaging/
    word-session.spec       # PyInstaller (two executables, onedir)
    installer.iss           # Inno Setup (optional)
    icons/
docs/                       # renamed from _docs/
    python_rules.md  docstring_schema.md  tests.md  development_guide.md
    user_guide.md  session_format.md  migration_plan.md
legacy/                     # old scripts kept read-only until Phase 7
```

Entry points:

- `word-session` → `word_session.cli:main` (console)
- `word-session-app` → `word_session.cli:app_main` (gui-scripts; tray +
  server, no console window)

### 3.3 Data model and session file format (v1)

```json
{
  "format": "word-session",
  "version": 1,
  "id": "20261031T143000-thesis-chapter-3",
  "name": "Thesis chapter 3",
  "kind": "manual",
  "pinned": false,
  "created_at": "2026-10-31T14:30:00+01:00",
  "host": "LAPTOP-123",
  "word_version": "16.0",
  "notes": "",
  "documents": [
    {
      "path": "C:\\Users\\me\\Documents\\ch3.docx",
      "location": "local",
      "position": { "start": 18234, "end": 18234, "page": 12, "line": 7 },
      "active": true,
      "read_only": false,
      "had_unsaved_changes": false,
      "window": { "state": "maximized" }
    }
  ]
}
```

Decisions:

- `kind`: `manual` | `auto` | `imported`. Retention applies only to `auto`.
- `location`: `local` | `unc` | `url` | `unsaved`. Existence checks only for
  `local`/`unc`; `unsaved` documents are listed in the file (so the user sees
  what was lost) but skipped on restore with a clear warning at capture time.
- `position.start/end` (character offsets, `Selection.Start/End`) are
  authoritative; `page/line` are a fallback when offsets exceed the document
  length (document was edited) and a human-readable hint in the UI.
- `active: true` marks the document that was in front; it is restored last
  so it ends up on top.
- Unknown fields are preserved on rewrite (forward compatibility); `version`
  gates migrations. Validation with `pydantic` models (also reused as HTTP
  schemas).
- Files: UTF-8, LF, written to `name.json.tmp` then `os.replace` (atomic on
  NTFS). Filename = `id + ".json"`; `id` = timestamp + slug, so lexical sort
  = chronological sort, and "latest" no longer depends on filesystem times.

### 3.4 Storage and configuration

Use `platformdirs` (already in the old venv):

| What | Location |
| --- | --- |
| Sessions | `%APPDATA%\word-session\sessions\` (roaming, user data) |
| Config | `%APPDATA%\word-session\config.toml` |
| Logs | `%LOCALAPPDATA%\word-session\logs\word-session.log` (rotating, 5 × 1 MB) |
| Instance info | `%LOCALAPPDATA%\word-session\instance.json` (port, token, pid) |

`config.toml` keys: `sessions_dir`, `autosave.enabled`,
`autosave.interval_minutes` (default 10), `autosave.keep` (default 20),
`autosave.only_on_change` (default true), `restore.start_word` (default
true), `restore.restore_position` (default true), `restore.open_timeout_s`
(default 60), `ui.start_at_login`.

On first run, `import-legacy` runs automatically (non-destructive copy) from
`~/.word-session/` and `~/.word-sessions/`; originals are never modified.

### 3.5 Word backend and COM resilience

This is where the tool succeeds or fails, so it gets its own design.

`WordBackend` protocol (all methods synchronous, all called on the COM
thread):

```python
class WordBackend(Protocol):
    def is_running(self) -> bool: ...
    def connect(self, start_if_needed: bool) -> None: ...      # raises WordUnavailable
    def list_documents(self) -> list[DocumentState]: ...
    def open_document(self, doc: DocumentState, *, read_only: bool) -> OpenOutcome: ...
    def restore_position(self, doc: DocumentState) -> None: ...
    def activate(self, path: str) -> None: ...
    def info(self) -> WordInfo: ...                            # version, visible, doc count
```

`ComWordBackend` rules:

1. **Late binding only**: `win32com.client.dynamic.Dispatch`; constants
   hard-coded in `word/constants.py`
   (`wdActiveEndPageNumber=3`, `wdFirstCharacterLineNumber=10`,
   `wdGoToPage=1`, `wdGoToLine=3`, `wdGoToAbsolute=1`, `wdGoToRelative=2`,
   `wdAlertsNone=0`, …). No `gen_py`, no cache corruption, trivially
   bundlable.
2. **Attach vs. start are distinct**: `GetActiveObject("Word.Application")`
   to attach (use the returned object); `Dispatch` only when starting is
   allowed. Note the known quirk that a freshly launched Word may not be in
   the ROT until its window has lost focus once — `connect` retries attach
   for a few seconds after a start.
3. **Capture without side effects**: read each document through
   `doc.Windows(1).Selection` (no `Activate()`); remember
   `ActiveDocument` and leave it untouched. Skip `ProtectedViewWindows`
   (recorded as `read_only`).
4. **One STA thread owns Word** (`ComWorker`): `pythoncom.CoInitialize()` on
   a dedicated thread; every front end submits jobs to a queue and waits on a
   future **with a timeout**. A stuck call (modal dialog in Word) surfaces as
   `WordNotResponding` to the caller while the worker keeps waiting; the UI
   stays responsive and tells the user "Word is showing a dialog".
5. **Busy retry**: register an `IMessageFilter`
   (`pythoncom.CoRegisterMessageFilter`) on the worker thread that retries
   `RPC_E_CALL_REJECTED` / `RPC_E_SERVERCALL_RETRYLATER` with backoff up to a
   limit, plus a decorator-level retry for the same HRESULTs as a fallback.
6. **Dialog suppression during restore**: save `DisplayAlerts`, set
   `wdAlertsNone`, open with `ConfirmConversions=False`,
   `AddToRecentFiles=False`, restore `DisplayAlerts` in `finally`.
7. **Per-document isolation**: each document opens in its own try/except;
   result recorded in `RestoreReport` as `opened | already_open | missing |
   locked | failed | skipped`, with the COM error text.
8. **Position restore**: `doc.Range(start, end).Select()` after clamping to
   `doc.Content.End`; fallback to page/line `GoTo` exactly as today; then
   `ScrollIntoView`.
9. **Integrity-level check**: COM between elevated and non-elevated
   processes fails with confusing errors; `doctor` detects and explains it.
10. **Release references** at the end of each job so Word can quit normally
    when the user closes it.

`FakeWordBackend` keeps an in-memory list of documents, can be scripted to
be "not running", "busy for N calls", "hang", or "fail on path X", and is
used by unit, CLI, API and UI tests and by `word-session app --demo`.

### 3.6 Service layer

`SessionService(store, backend_runner, settings, clock)`:

- `capture(name=None, kind="manual") -> Session` — also returns warnings
  (unsaved documents, no documents open).
- `restore(selector, only=None, start_word=True, restore_position=True,
  dry_run=False) -> RestoreReport` — `only` supports the partial restore the
  wx prototype was sketching.
- `list()`, `get(selector)`, `rename`, `delete` (to a `trash/` subfolder,
  recoverable), `pin`, `prune()`, `import_legacy(paths)`, `diff(a, b)`.
- `autosave_tick()` — capture only if the document set or positions changed
  since the last auto-session (hash compare), then prune.

Selectors: id, unique id prefix, exact name, file path, `latest`,
`latest-manual`, `-N`.

`clock` is injected so tests control timestamps.

### 3.7 CLI

argparse (stdlib, already in use) with subcommands; `main(argv=None) -> int`
and `sys.exit(main())`.

```
word-session save [--name NAME] [--file PATH]
word-session restore [SELECTOR] [--only GLOB ...] [--no-start] [--no-position] [--dry-run]
word-session load ...                     # alias of restore (compatibility)
word-session current                      # documents open in Word now (replaces GetDocuments)
word-session list [--limit N] [--kind manual|auto|imported]
word-session show SELECTOR
word-session rename SELECTOR NEW_NAME
word-session delete SELECTOR [--purge]
word-session pin|unpin SELECTOR
word-session prune [--keep N]
word-session import-legacy [DIR ...]
word-session doctor                       # Python/pywin32/Word/ROT/elevation/paths/log location
word-session open                         # open the manager of the running app in the browser
word-session serve [--port P] [--open]    # API + UI in a browser, no tray
word-session app [--demo]                 # tray + server (what the shortcut runs)
global: --json  --verbose/-v  --quiet  --config PATH  --sessions-dir DIR
```

Exit codes: `0` ok, `1` unexpected error, `2` usage, `3` Word unavailable,
`4` partial restore (some documents failed), `5` session not found,
`6` Word not responding (timeout).

Human output is concise; `--json` emits the model objects for scripting.
Tracebacks go to the log; the console gets one actionable line unless `-v`.

### 3.8 Local HTTP API and visual manager

Server: **FastAPI + uvicorn** run in a background thread (recommended:
pydantic schemas shared with the model, `TestClient` for tests; adds a few MB
to the bundle). Minimal-dependency alternative: stdlib
`ThreadingHTTPServer` with a tiny router — viable, but more hand-written
validation and test plumbing.

Security (the API can make Word open arbitrary files, and the UI lives in the
same browser as arbitrary web pages, so other sites must not be able to drive
it):

- bind `127.0.0.1` only, random free port;
- the manager is opened at `http://127.0.0.1:PORT/login?code=…` with a
  **single-use, short-lived code** (minted by the tray or CLI each time it
  opens the UI); the server exchanges it for an `HttpOnly`,
  `SameSite=Strict` session cookie and redirects to `/`, so the URL left in
  browser history is useless;
- every API call requires that cookie **and** a custom header
  (`X-Word-Session: 1`, set by `app.js`), which cross-site forms cannot send
  without a CORS preflight that the server never approves;
- reject requests whose `Host` is not `127.0.0.1:PORT`/`localhost:PORT`
  (DNS rebinding), and state-changing requests whose `Origin` is present and
  foreign; no CORS headers; `Content-Security-Policy: default-src 'self'`.

Endpoints:

```
GET    /api/health
GET    /api/word                     running?, version, doc count
GET    /api/word/documents           live documents (current)
GET    /api/sessions                 list (filters: kind, pinned, q)
POST   /api/sessions                 capture {name?}
GET    /api/sessions/{id}            detail incl. per-doc existence
PATCH  /api/sessions/{id}            rename / pin / notes / remove documents
DELETE /api/sessions/{id}
POST   /api/sessions/{id}/restore    {only?, start_word?, restore_position?} -> job id
GET    /api/jobs/{id}                progress + RestoreReport
GET    /api/events                   SSE: job progress, Word state, autosave
GET    /api/settings | PUT /api/settings
POST   /api/import-legacy
GET    /api/logs?tail=200
```

Restores run as jobs so the UI shows per-document progress over SSE.

UI (static HTML + vanilla JS modules, vendored, no Node build, works
offline):

- **Sessions**: table of name, date, kind badge, document count, missing
  count, pin; search; "Save current session" button.
- **Session detail**: documents with checkboxes (partial restore),
  existence/location badges, position hint ("p. 12, l. 7"), restore
  selected, remove from session, rename, notes.
- **Now in Word**: live document list, "Save as…".
- **Settings**: autosave interval/keep, sessions folder, start at login,
  "import old sessions".
- **Diagnostics**: `doctor` output and log tail, "copy for bug report".

Light/dark via `prefers-color-scheme`; keyboard navigable.

### 3.9 Process model (tray + browser)

- **App process** (`word-session-app.exe`, windowed): owns the ComWorker,
  the HTTP server, the autosave scheduler and the tray icon (`pystray`, run on
  the main thread; server and worker on background threads). Single instance
  via a named mutex `Local\WordSession.App`; a second launch reads
  `instance.json`, asks the running instance (local API call) for a fresh
  login code, opens the manager in the browser, and exits.
- **Manager UI**: "Open manager…" (tray, double-click on the icon, or
  `word-session open` from the CLI) mints a login code and calls
  `webbrowser.open(...)`. The tab is just a client; closing it costs nothing,
  and the server keeps running in the tray process.

Why the default browser rather than an embedded window: no GUI toolkit to
ship or debug (no `pywebview`/`pythonnet`/WinForms, no main-thread
contention with the tray), zero extra install size, and the UI is the same
page whether opened from the tray, the CLI, or bookmarked. Costs accepted: the
manager is a tab among others rather than its own taskbar entry, and the
tray cannot focus an already-open tab, so it opens a new one. If a
standalone window is wanted later, `msedge --app=URL` can be offered as a
setting without any code changes to the UI.

Multiple tabs are first-class:

- Opening a new tab never invalidates existing ones. A login code only adds
  a server-side session; all sessions stay valid until the app quits.
- Every tab subscribes to `/api/events`, so a capture, restore, rename or
  autosave made in one tab (or from the tray/CLI) shows up in all of them.
- Edits carry the session file's revision (`ETag` / `If-Match` on `PATCH`
  and `DELETE`); a conflicting edit gets `412` and the tab reloads that
  session instead of silently overwriting another tab's change.
- When the app is quit or restarted, open tabs lose the connection and show
  "Word Session is not running — reopen it from the tray"; they do not try
  to guess the new port.

Tray menu:

```
Save session now
Restore latest session
Recent sessions ▸  (last 8, pinned first)
Open manager…
──────────
Autosave: on/off   (checkable)
Start at login     (checkable)
Open sessions folder / Open log
──────────
Quit
```

Icon states: idle / working (during capture/restore) / warning (Word not
responding, last autosave failed). Balloon notifications for restore reports
with failures.

### 3.10 Logging and diagnostics

- `logging` everywhere; rotating file handler always on; console handler
  only for the CLI.
- Every COM job logs start/end/duration/HRESULT.
- Unhandled exceptions in tray/server threads are logged and shown as a tray
  warning instead of killing the process silently.
- `doctor` checks: Python/pywin32 versions, Word ProgID registered, Word in
  ROT, elevation mismatch, sessions dir writable, config parse, legacy dirs
  present, running app instance reachable.

---

## 4. Testing strategy

Create `docs/tests.md` (referenced by `AGENTS.md` but missing) describing
this. Tooling: `pytest`, `pytest-cov`, `ruff` (lint + format), `pyright` or
`mypy --strict` on `src/`.

| Level | What | Needs Word | Runs in CI |
| --- | --- | --- | --- |
| Unit | model validation, store (atomic write, sort, prune, trash, corrupt-file tolerance), legacy readers, selectors, config, service logic with `FakeWordBackend` and fake clock | no | yes |
| Contract | one parametrised suite asserting `WordBackend` behaviour; runs against `FakeWordBackend` always and `ComWordBackend` when Word is available — keeps the fake honest | optional | fake only |
| Worker | `ComWorker` timeouts, retry on simulated busy HRESULTs, error propagation, shutdown | no | yes |
| CLI | `main([...])` with `capsys`, exit codes, `--json` output snapshots | no | yes |
| API | `TestClient`: auth/token/Host checks, endpoints, job lifecycle, SSE | no | yes |
| UI | Playwright against `serve --demo` (fake backend): list, detail, partial restore, settings | no | optional nightly |
| Integration | real Word: generate `.docx` fixtures in `tmp_path` via COM, capture, close, restore, assert positions; missing file; locked file (second handle); unsaved doc; already-open doc | yes | marked `@pytest.mark.word`, skipped unless `WORD_SESSION_TEST_WORD=1` on a Windows box with Word |
| Packaging smoke | built exe: `--version`, `doctor --json`, `serve --demo` responds | no | yes (Windows runner) |

Fixtures: real legacy files in `tests/fixtures/legacy/` — a Python v0 file,
a UTF-16 PowerShell file, a PowerShell file with a single document, a
truncated/corrupt file, a file with non-ASCII paths.

Coverage gate: ≥ 90 % for `model`, `store`, `legacy`, `service`, `cli`,
`web`; COM module covered by the integration suite only.

CI: GitHub Actions `windows-latest`, `uv sync --frozen`, ruff, type check,
pytest (without `word` marker), PyInstaller build, smoke test, upload
artifact.

---

## 5. Packaging and distribution

- **Python 3.13** pinned (`requires-python = ">=3.13,<3.14"`) until
  `pywin32` and PyInstaller are confirmed on 3.14 (no `pythonnet` dependency
  any more, so the move should be cheap). Managed with `uv` (available on this
  machine; the old venv is unusable and should be deleted).
- Runtime deps: `pywin32`, `platformdirs`, `pydantic`, `fastapi`,
  `uvicorn`, `pystray`, `Pillow`. Dev deps: `pytest`,
  `pytest-cov`, `ruff`, `pyright`, `httpx`, `playwright`, `pyinstaller`.
  Drop `wxPython` and the Jupyter stack.
- **PyInstaller onedir** (faster start, fewer antivirus false positives than
  onefile, matters for a tray app launched at login), two executables in one
  folder sharing the bundle: `word-session.exe` (console) and
  `word-session-app.exe` (windowed). UPX off (AV heuristics).
- Version from `pyproject.toml`, exposed by `--version` and in the UI.
- Per-user install to `%LOCALAPPDATA%\Programs\WordSession` with Inno Setup:
  Start menu shortcut ("Word Session"), optional "start at login",
  uninstaller that leaves sessions in place. A plain zip is published too.
- Optional later: code signing to avoid SmartScreen warnings.

---

## 6. Phased migration

Each phase ends in a working, committed state. Rough effort for one
developer in parentheses.

### Phase 0 — Baseline and hygiene (½ day)

1. First commit of the repo exactly as it is; tag `legacy-baseline`. Rename
   branch to `main`.
2. Move old scripts to `legacy/` (`legacy/python/` from `new/distrib/`,
   `legacy/powershell/` with the `.ps1` and `.cmd`); delete the root and
   `new/` duplicates (identical, non-compiling copies of `new/distrib/`).
   The wx prototype goes to `legacy/` as UI reference only.
3. Delete `venv/`; add `venv/`, `.venv/`, `build/`, `dist/` to `.gitignore`.
4. Rename `_docs/` → `docs/` so `AGENTS.md` paths resolve; add
   `docs/tests.md`; fill `development_guide.md` (setup with `uv`, running
   tests, Word integration tests).
5. Re-encode requirement files as UTF-8 (then replace them with
   `pyproject.toml` in Phase 1).

Exit: clean history, `AGENTS.md` links valid, nothing duplicated.

### Phase 1 — Package skeleton, model, store, legacy import (1–2 days)

1. `pyproject.toml`, `src/word_session/`, ruff/pyright/pytest config, CI
   workflow.
2. `model.py`, `store.py` (atomic writes, listing, selectors, prune, trash),
   `legacy.py` (both legacy formats, BOM/encoding detection, single-object
   tolerance), `config.py`.
3. Unit tests + legacy fixtures, including the user's real old session files
   (copied, not moved).

Exit: `pytest` green in CI; every legacy file on this machine imports to v1.

### Phase 2 — Word backend (2–3 days)

1. `WordBackend` protocol, `FakeWordBackend`, `constants.py`.
2. `ComWordBackend`: late binding, attach/start, side-effect-free capture,
   per-doc open with alerts suppressed, offset-based positioning with
   page/line fallback.
3. `ComWorker`: STA thread, job queue, timeouts, message filter + retry.
4. Contract suite (fake in CI; real Word locally) and integration tests with
   generated `.docx` fixtures.

Exit: integration suite green on a machine with Word, including missing,
locked, unsaved, already-open and cloud-path cases; capture verified not to
change the active document.

### Phase 3 — Service and CLI parity (1–2 days)

1. `SessionService` with `RestoreReport`.
2. `cli.py` with all subcommands, `--json`, exit codes, logging.
3. Automatic first-run legacy import.
4. Replace the three `.cmd` files with shims that call `word-session.exe`
   (`save`, `restore`, `current`) so existing shortcuts keep working.

Exit: everything the old Python and PowerShell tools did works through the
new CLI, plus `list/show/current/doctor`; CLI tests green.

### Phase 4 — HTTP API and web UI (3–4 days)

1. `web/app.py` with auth, endpoints, jobs, SSE; API tests.
2. Static UI (Sessions, Detail with partial restore, Now in Word, Settings,
   Diagnostics).
3. `word-session serve [--open] [--demo]`.
4. Playwright smoke tests against `--demo`.

Exit: full session management in a browser against real Word; API rejects
requests without token or with a foreign `Host`.

### Phase 5 — Desktop shell: tray, autosave (1½–2 days)

1. `instance.py` (mutex + `instance.json`), `tray.py`, `autostart.py`,
   `word-session open` (mint login code, open default browser).
2. Autosave scheduler (change detection, retention, failure backoff,
   paused while a restore job runs).
3. Tray notifications for restore reports and autosave failures.

Exit: `word-session app` runs for a working day with autosave on, survives
Word being closed/reopened/hung; a second launch opens the manager of the
running instance instead of starting another.

### Phase 6 — Packaging and release (1–2 days)

1. PyInstaller spec for both executables, icons, version resource.
2. Inno Setup installer; zip artifact; CI build + smoke test.
3. `docs/user_guide.md`, `docs/session_format.md`, changelog. Release
   `v1.0.0`.

Exit: installs on a clean Windows 11 user account without Python; shortcuts
and start-at-login work; uninstall keeps sessions.

### Phase 7 — Decommission legacy (½ day, after ~2 weeks of real use)

Remove `legacy/` (still available at the `legacy-baseline` tag) and the
`.cmd` shims if no longer used. Keep the legacy *readers* permanently.

### Phase 8 — Optional enhancements

- **Save on Word quit**: subscribe to `Application.DocumentBeforeClose` /
  `Quit` events via `DispatchWithEvents` (needs type information; isolate it
  in its own module so the rest stays late-bound) to snapshot the session
  right before the user closes Word — the strongest "recover my workspace"
  feature.
- Session diff/merge, tags, restoring window placement and zoom.
- Global hotkey for "save session now".
- Export/share a session as a zip of paths (+ optionally files).

---

## 7. Compatibility guarantees

- Old session files (both formats, both directories) are read forever and
  imported without modifying the originals.
- `word-session load` stays an alias of `restore`; `.cmd` shims keep the
  old file names working through Phase 6.
- The v1 format carries `version`; future versions add migrations in
  `legacy.py`/`store.py` and always read older versions.

---

## 8. Risks

| Risk | Mitigation |
| --- | --- |
| Word modal dialogs block COM indefinitely | dedicated worker + caller timeouts; `DisplayAlerts` off; UI reports "Word is waiting for you" |
| Word not in ROT right after start | retry attach for a few seconds after `Dispatch` |
| Positions drift after edits | offsets primary, page/line fallback, clamp to document end |
| Manager tab lost among browser tabs | tray double-click opens another tab (old ones keep working); optional `msedge --app` setting |
| Two tabs edit the same session | live updates via SSE; `If-Match` revisions turn conflicts into a reload, not a lost edit |
| AV flags the PyInstaller exe | onedir, no UPX, optional signing |
| Elevation mismatch breaks COM | `doctor` detection and message |
| Local API abused by other web pages in the same browser | localhost bind, one-time login code → `SameSite=Strict` cookie, required custom header, Host/Origin checks, no CORS |
| Scope creep in the UI | Phase 4 ships the five screens above, nothing more |

---

## 9. Decisions to confirm

1. **Sessions directory**: `%APPDATA%\word-session\sessions` (recommended)
   vs. keeping `~/.word-session`.
2. **Web stack**: FastAPI + uvicorn (recommended) vs. stdlib-only server.
3. **Manager UI host**: default browser (decided 2026-10-31); `msedge --app`
   window as a possible later setting.
4. **Python version**: 3.13 pinned (recommended) vs. 3.14.
5. **Distribution**: per-user Inno Setup installer + zip (recommended) vs.
   zip only.
