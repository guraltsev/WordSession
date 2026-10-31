# Word Session 1.0.0 acceptance checklist

Written by job 23 on 2026-10-31. Work through this in one sitting. Fill the
Result column with pass / fail / notes. Step numbers (for example `C4`) are
what you quote in a bug report.

## 1. Setup

**Before you start, end the leftover processes** (they are hidden test helpers,
the sandbox could not kill them):

- Nine hidden `WINWORD.EXE /Automation -Embedding` processes from job 14:
  PIDs 70684, 15024, 62392, 61516, 73048, 71828, 73376, 74820, 75576. End them
  in Task Manager. Keep your own Word (PID 60884 when the run started).
- Stray demo `word-session-cli.exe --demo serve` processes (PIDs 17456, 68768 at the
  time; another `word-session.exe` PID 70648 was running at the end of job 23).
  They lock `.venv\Scripts\word-session.exe`, which breaks `uv sync`.

**Built bundle.** `dist\WordSession\` (and `dist\WordSession-0.1.0-win64.zip`)
exist from job 23's `packaging\build.ps1 -NoSync`. The bundle is labelled
**0.1.0**, not 1.0.0 (see known issue K1). After ending the strays run
`uv sync` and `powershell -File packaging\build.ps1` to get a 1.0.0 bundle. The
installer (`.\packaging\build.ps1 -Installer`) needs Inno Setup 6
(`winget install JRSoftware.InnoSetup`); it has never been compiled.

**Run from source** (repository root):

```text
uv sync
uv run word-session-cli --version
uv run word-session-cli list
```

If `uv sync` or `uv run` fails because `word-session.exe` is locked, use
`uv run --no-sync ...`.

**Throwaway data versus real data.** All data lives under one root that
`WORD_SESSION_HOME` overrides. For testing use a throwaway folder in the same
console:

```text
set WORD_SESSION_HOME=%TEMP%\ws-test
```

Without it the tool uses your real folders: sessions in
`%APPDATA%\word-session\sessions\`, settings in
`%APPDATA%\word-session\config.toml`, log in
`%LOCALAPPDATA%\word-session\logs\word-session.log`. Unset the variable
(`set WORD_SESSION_HOME=`) for the real-data steps (start at login, installer).
`--demo` before the command (for example `word-session-cli --demo serve`) uses a
fake Word with three demo documents.

**Sample documents.** `python scripts/make_test_docs.py` prints a folder with
`alpha.docx`, `beta.docx`, `gamma.docx`, `with space é.docx` (about ten pages
each). Open them in your Word for the CLI steps.

**Logs.** `%LOCALAPPDATA%\word-session\logs\word-session.log` (or `logs\` under
`WORD_SESSION_HOME`). Tray menu: "Open log". Browser: Diagnostics page.

## 2. Automated results (job 23, 2026-10-31)

| Command | Result | Counts |
| --- | --- | --- |
| `ruff format --check .` | pass | 79 files already formatted |
| `ruff check .` | pass | all checks passed |
| `pyright` | pass | 0 errors, 0 warnings |
| `pytest --cov=word_session` (`-p no:faulthandler`) | pass | 358 passed, 48 skipped (real-Word/UI tests), 0 failed; total coverage 88% |
| `WORD_SESSION_TEST_WORD=1 pytest -m word` | pass | 36 passed, 0 failed; no new WINWORD.EXE left behind |
| `WORD_SESSION_TEST_SHARED_WORD=1 pytest -m shared_word` | pass | 4 passed, 0 skipped; your Word reachable; no new WINWORD.EXE |
| `WORD_SESSION_TEST_UI=1 pytest -m ui` | pass | 8 passed |
| `packaging\build.ps1 -NoSync` | pass with caveat | zip built, but named 0.1.0 (K1) |
| `packaging\smoke_test.ps1 -Dist dist\WordSession` | pass | `--version` prints `word-session 0.1.0`, doctor JSON, save, list, serve health |
| `packaging\build.ps1 -Installer` | not run | Inno Setup absent (K2) |

(Without `-Dist` the smoke script stops: the parameter is mandatory.)

Coverage per module (statements, missed, cover):

| Module | Stmts | Miss | Cover |
| --- | --- | --- | --- |
| `__init__` | 6 | 2 | 67% |
| `__main__` | 2 | 2 | 0% |
| `app` | 108 | 14 | 87% |
| `autosave` | 82 | 1 | 99% |
| `autostart` | 40 | 2 | 95% |
| `cli` | 323 | 6 | 98% |
| `config` | 79 | 5 | 94% |
| `doctor` | 97 | 7 | 93% |
| `events` | 26 | 0 | 100% |
| `instance` | 117 | 11 | 91% |
| `legacy` | 111 | 0 | 100% |
| `logging_setup` | 31 | 1 | 97% |
| `model` | 76 | 0 | 100% |
| `service` | 241 | 5 | 98% |
| `store` | 137 | 0 | 100% |
| `tray` | 139 | 5 | 96% |
| `web/app` | 279 | 2 | 99% |
| `web/auth` | 36 | 0 | 100% |
| `web/jobs` | 62 | 0 | 100% |
| `web/server` | 40 | 4 | 90% |
| `web/sse` | 23 | 1 | 96% |
| `word/backend` | 24 | 0 | 100% |
| `word/constants` | 15 | 0 | 100% |
| `word/fake` | 122 | 0 | 100% |
| `word/worker` | 148 | 12 | 92% |
| `word/com` | 269 | 232 | 14% (needs real Word; exercised by the `word` tests, which were not part of the coverage run) |
| Total | 2636 | 312 | 88% |

## 3. Manual checks

Use a throwaway `WORD_SESSION_HOME` unless a step says otherwise. Commands use
`uv run word-session`; the bundle's `word-session.exe` works the same.

### A. CLI with real Word

| # | Step and exact command | Expected | Result |
| --- | --- | --- | --- |
| A1 | Run `python scripts/make_test_docs.py`, open the printed folder. | Four documents of about 10 pages. | |
| A2 | With Word and a few documents open: `uv run word-session-cli save`, close the documents, `uv run word-session-cli restore`. | Documents reopen, exit code 0, cursors restored. | |
| A3 | After A2 compare capture order with the order Word opened them (oldest first); check the active document and cursor did not change while listing. | Order matches, active document unchanged. | |
| A4 | If shared-Word tests skipped with the ROT reason: click away from Word once, then `set WORD_SESSION_TEST_SHARED_WORD=1` and `uv run pytest -m shared_word`. | Tests run and pass. | |
| A5 | Modal dialog timeout: open File > Options in Word, run `uv run word-session-cli current --json`. | Exit 6 within the timeout; Word untouched. | |
| A6 | `--no-start` with Word closed: close Word, run `uv run word-session-cli restore --no-start`. | Exit 3, and Word does not start. | |
| A7 | With Word closed: `uv run word-session-cli current`. | `error: Word is not running`, exit 3. | |
| A8 | With Word running: `uv run word-session-cli doctor`. | All `ok`, exit 0. | |
| A9 | Start Word as administrator, run `doctor` from a normal console. | `word-process` FAIL with the privilege-level message, exit 1. | |
| A10 | `word-session-WriteSession.cmd` and `word-session-GetDocuments.cmd` from `dist\WordSession` with Word open. | Session saved / documents listed; window pauses only on error. | |
| A11 | `word-session-LoadSession.cmd` with no argument, then with a session file path. | Latest / that session restored. | |


### C. Browser manager

Start with `uv run word-session-cli --demo serve --open` (temporary home).

| # | Step | Expected | Result |
| --- | --- | --- | --- |
| C1 | Browser opens. | Sessions page (empty list message), header "Word 16.0 running" with a green dot. | |
| C2 | "Save current session", with and without a name. | Toast, new row with local creation time, kind badge "manual", 3 documents. | |
| C3 | Open a row; rename, pin, edit and save notes. | Changes appear; the list reflects them. | |
| C4 | Untick one document, "Restore selected". Then use the list's "Restore" button. | Progress bar then per-document badges ("already_open" in demo). The list button opens the detail page and restores all. | |
| C5 | Two browser tabs: open a second tab as a new login (`word-session-cli open`, or another login code via `POST /api/internal/login-code`). In tab A rename a session. | Tab B's list updates within about 0.5 s without reload. | |
| C6 | Edit in A, then save in a stale B detail page. | Toast "This session was changed in another tab; showing the latest version." | |
| C7 | "Delete session". | Confirm dialog (Escape cancels, Delete moves to trash), returns to list. | |
| C8 | Ctrl+C the server while the tab is open. | Red banner "Word Session is not running — reopen it from the tray". | |
| C9 | Restart `serve` on the same port (`--port N`). | Banner clears; page says "Not signed in. Open the manager from the tray icon or run `word-session-cli open`." | |
| C10 | Switch OS to dark mode and back; tab through every screen; narrow to 360 px. | Colours follow the theme, focus outline visible, all buttons reachable, tables scroll sideways, no page-wide overflow. | |
| C11 | Settings: change the autosave interval, Save; then enter 0. | Toast "Settings saved."; the 0 gives an error toast naming the field. | |
| C12 | Diagnostics page; "Copy report"; paste into an editor. | Table of checks and log tail shown; pasted text has checks first, then log lines. | |
| C13 | Real Word closed, `serve` without `--demo`: "Open now". | "Word is not running." and a red dot. "Restore" on a session starts Word (unless `--no-start`). | |
| C14 | Start Word normally (start screen, no document open), then open "Open now" and Diagnostics. | Word is shown as running with 0 documents; no console window flashes on Diagnostics. | |
| C15 | Open two documents in Word. On "Open now" tick one, press "Save selected as session…", then "Close now" and confirm. | The session holds only the ticked document; the ticks are still set after saving; only that document closes. A document with unsaved changes stays open and is reported. | |

### D. Tray

| # | Step | Expected | Result |
| --- | --- | --- | --- |
| D1 | `uv run word-session-cli --demo app --open`. | Tray icon (white page, blue bookmark) appears; browser opens signed in. | |
| D2 | In another console `uv run word-session-cli --demo open`. | New tab opens signed in; old tab still works; no second tray icon. | |
| D3 | Double-click the icon. | A tab opens. | |
| D4 | Menu "Save session now". | Balloon notification "Saved 3 documents". | |
| D5 | Menu "Recent sessions". | Newest first, pinned first; clicking restores. | |
| D6 | Menu "Open sessions folder", "Open log". | Explorer folder / log file opens. | |
| D7 | Menu "Quit". | Icon disappears; `instance.json` removed from the state folder. | |
| D8 | Start the app a second time with the first running (Start menu or `word-session`). | Existing instance opens a tab; the second process exits silently. | |
| D9 | Kill the app in Task Manager, then `word-session-cli open`. | Stale instance file ignored; app starts and opens the manager. | |
| D10 | Look at the three icon colours (blue, amber, red). | Acceptable. | |
| D11 | Notifications: trigger a save from the tray, and an autosave failure if you can (see K9). | Balloons appear with sensible text. | |

### E. Autosave

| # | Step | Expected | Result |
| --- | --- | --- | --- |
| E1 | `word-session-cli --demo app`; set interval 1 minute in Settings with a changing demo state. | An `auto` session appears within about a minute. | |
| E2 | Untick "Autosave" in the tray. | No new `auto` sessions appear. | |
| E3 | Real Word, real home: leave autosave on for a few intervals while editing. | `auto` sessions appear only when the document set changes. | |

### F. Start at login

| # | Step | Expected | Result |
| --- | --- | --- | --- |
| F1 | Tray menu: tick "Start at login". Check `reg query HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v WordSession`. | Value exists with the quoted exe path. | |
| F2 | Sign out and in. | Tray app starts by itself. | |
| F3 | Untick "Start at login". | The `WordSession` value is removed. | |

### G. Packaging and installer

| # | Step | Expected | Result |
| --- | --- | --- | --- |
| G1 | After ending the strays: `uv sync`, then `powershell -File packaging\build.ps1`. | Zip built, named 1.0.0. | |
| G2 | Double-click `dist\WordSession\word-session.exe` (or a shortcut with `--demo`); quit from the tray. | Tray icon, manager opens with styling. | |
| G3 | Explorer: exe icon and Properties > Details. | Icon shown; version 1.0.0 (it said 0.1.0 in the job 20 build). | |
| G4 | `winget install JRSoftware.InnoSetup`, then `powershell -File packaging\build.ps1 -Installer`. | `dist\WordSession-1.0.0-setup.exe`, no compile errors or warnings. | |
| G5 | Silent install: `setup.exe /VERYSILENT /SUPPRESSMSGBOXES /CURRENTUSER /DIR=<tmp> /TASKS=""`. | Files in `<tmp>`; `<tmp>\word-session-cli.exe --version` prints `word-session 1.0.0`; no Run value. | |
| G6 | Start `word-session.exe` with `WORD_SESSION_HOME=<tmp2>` and `--demo`, run the installer again over it. | The app is stopped (`quit-app`) and files replaced. | |
| G7 | Silent uninstall `<tmp>\unins000.exe /VERYSILENT`. | Folder gone, `<tmp2>` untouched. | |
| G8 | Interactive install. Start menu entry "Word Session". With the start-at-login task ticked check `HKCU\...\Run\WordSession`; unticked, none. | Entry launches the tray app and opens the manager; Run value present or absent as chosen; app starts after sign-in. | |
| G9 | Interactive uninstall. | Final page says sessions and settings were kept and names both folders; Run value removed; running tray app stopped first. | |
| G10 | Read `docs/user_guide.md` against the real UI. | Accurate. | |

## 4. Known issues and deviations

### Known issues

- **K1. Version mismatch.** `pyproject.toml` says 1.0.0 but the venv's installed
  metadata still says 0.1.0 (a locked `.venv\Scripts\word-session.exe` blocks
  `uv sync`). `word-session-cli --version` and bundles built from the venv say
  0.1.0. A clean `uv sync` after the strays end fixes it. Not worked around.
- **K2. Installer never compiled.** Inno Setup (`iscc.exe`) is not installed
  (decision D5). Job 21 is `partial`: `installer.iss` and the `-Installer`
  switch are untested (steps G4 to G9). It needs Inno Setup 6.3+
  (`ArchitecturesAllowed=x64compatible`).
- **K3. Leaked processes.** The nine hidden Word processes and the stray demo
  `serve` processes (section 1) could not be killed by the agents.
- **K4. No remote CI run.** Job 03's workflow has never run (no GitHub remote).
- **K5. Faulthandler noise.** Real-Word runs need `-p no:faulthandler`; otherwise
  pytest prints harmless "Windows fatal exception 0x800706be/ba" traces at Word
  shutdown (not set in `pyproject.toml`).
- **K6. Unproven Word interference (job 14).** While debugging, a helper
  `DispatchEx` Word sometimes seemed to take down another Word. Root cause not
  proven; fixture ordering mitigates it. Watch for it in A-steps.
- **K7. `doctor.py` SyntaxWarning (job 09 finding).** Invalid `\W` escape in a
  docstring near line 204; not seen in the final test run (1 unrelated
  warning, httpx in Starlette), recheck.
- **K8. Smoke script argument.** `smoke_test.ps1` requires `-Dist`; the job text
  runs it without one.
- **K9. Autosave warning clearing (job 19).** A tick that saves nothing counts as
  success for backoff; the tray warning clears only on an `auto` save.
- **K10. UI test browser (job 17).** `playwright install chromium` printed nothing
  and the browser already existed; a fresh download was not verified.
- **K11. `docs/development_guide.md`** does not mention `-Installer`.
- **K12. `word/com.py` coverage 14%** in the plain coverage run (it only runs
  under the `word` marker).

### Blocked jobs

None. Job 21 is the only `partial` (K2). Job 22 (remove `legacy/`) waits for you.

### Coordinator fixes and job-text changes (`CHANGES.md`)

- Job 00 baseline commit 9841936 pre-existed; renamed to `main`, tagged `legacy-baseline`.
- Job 02: ruff format rewrote job texts 04-19; the coordinator restored them,
  and `[tool.ruff.format] exclude = ["*.md"]` was added.
- Job 06: `.gitattributes` `-text` rule for `tests/fixtures/legacy/*` (exact bytes).
- Job 15 to 16: EventSource cannot send `X-Word-Session`; job 16 text edited to
  use fetch-streamed SSE (header rule kept).
- Job 09: 30 word and shared_word tests re-run by the coordinator, passed.
- Job 16: stray demo serve PIDs 17456 and 68768 not killable (K3).
- D5: no `iscc.exe`; zip is the verified artifact (K2).
- Job 14: nine leaked Word PIDs; e2e tests re-run, 10 passed, no new leaks.
- Job 21 accepted as done under the D5 fallback although reported `partial`.

### Deviations that change behaviour

- Store (05): invalid ids with path separators are rejected; selectors beyond
  range raise `SessionNotFound`.
- Config (07): nested settings also reject unknown keys; unusable log dir falls
  back to a WARNING console handler.
- COM (09): documents listed oldest first (Word returns newest at index 1);
  restore keeps the previously active document; offsets clamped to
  `Content.End - 1`; isolated `connect(start_if_needed=False)` raises
  `WordUnavailable` when no process exists.
- Service (11): restore connects to Word only when a document needs it; an empty
  capture returns a Session with id `""` (never stored); autosave builds the
  candidate once and writes nothing when unchanged.
- CLI (12): `save` prints `->`; `-q` suppresses all human stdout; global options
  must precede the command; negative `list --limit` gives an empty list.
- CLI (13): `delete` declined exits 1 `cancelled`, non-TTY without `--yes` exits 2;
  `word-process` is `ok` with no WINWORD process; `config` check ignores
  `--config`; first-run import errors only log a warning.
- HTTP (15): `/api/internal/*` all need the secret header; `/api/logs?tail=`
  outside 1..1000 gives 422; request bodies reject unknown fields.
- Web UI (16): partial restore sends glob-escaped paths; the list's pin toggle has
  no stale-edit detection; `serve --json` prints `{"url", "stopped"}`.
- Tray/app (18): `app` and `open` ignore `--config` and `--sessions-dir` (only
  `--demo` forwarded); the "working" icon covers tray actions only, not
  browser-started restores; `open` prints a URL only if an instance answered.
- Autosave (19): the first tick happens after one full interval.
- Packaging (20): extra `-NoSync` and `-SkipServe` switches; `build.ps1` retries
  zipping; smoke test kills `serve` (no shutdown endpoint wired for `serve`).
- Installer (21): `quit-app` runs whenever `word-session.exe` exists.

## 5. How to report a bug

1. Run `uv run word-session-cli doctor --json` (or `word-session-cli.exe doctor --json`).
2. Attach the last 100 lines of `%LOCALAPPDATA%\word-session\logs\word-session.log`
   (or the log under your `WORD_SESSION_HOME`).
3. Note the checklist step number (for example `C5`), what you did, what you
   expected and what happened.

## 6. After testing

- When satisfied, tag the release: `git tag v1.0.0`.
- Ask for job 22 to remove `legacy/`.
