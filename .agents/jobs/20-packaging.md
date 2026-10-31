# Job 20 — Packaging (PyInstaller) and legacy `.cmd` shims

Depends on: 19
Plan reference: §5, §6 Phase 3 step 4 and Phase 6 step 1
Decisions: D5

## Goal

Build a self-contained Windows bundle — a console `word-session.exe` and a
windowed `word-session-app.exe` sharing one folder — and keep the old
`.cmd` entry points working on top of it.

## Files

- `pyproject.toml` (dev dep `pyinstaller>=6.10`)
- `packaging/word-session.spec`
- `packaging/entry_cli.py`, `packaging/entry_app.py`
- `packaging/version_info.py` (generates the Windows version resource from
  the package version)
- `packaging/build.ps1`
- `packaging/shims/word-session-WriteSession.cmd`,
  `word-session-LoadSession.cmd`, `word-session-GetDocuments.cmd`
- `packaging/smoke_test.ps1`
- `.github/workflows/ci.yml` (replace the job 03 placeholder comment)
- `docs/development_guide.md` (build section)

## Do

1. Entry scripts: `entry_cli.py` → `from word_session.cli import main;
   raise SystemExit(main())`; `entry_app.py` → `from word_session.cli import
   app_main; app_main()`.
2. Spec (onedir, plan §5):
   - two `Analysis` objects (or one shared, PyInstaller "multipackage"
     pattern) and two `EXE`s: `word-session` (`console=True`) and
     `word-session-app` (`console=False`), `icon=packaging/icons/app.ico`,
     `upx=False`, `version=` resource from `version_info.py`;
   - one `COLLECT` named `WordSession` containing both;
   - `datas`: `src/word_session/web/static` → `word_session/web/static`,
     `src/word_session/assets` → `word_session/assets`;
   - `hiddenimports`: `win32timezone` (pywin32), uvicorn's dynamically
     imported modules (`uvicorn.logging`, `uvicorn.loops.auto`,
     `uvicorn.protocols.http.auto`, `uvicorn.protocols.websockets.auto`,
     `uvicorn.lifespan.on`), `pystray._win32`;
   - `excludes`: `tkinter`, `wx`, `IPython`, `jupyter_client`, `matplotlib`.
3. Static files must be found when frozen: verify the
   `importlib.resources` lookups from jobs 15/18 work in the bundle; if not,
   fix them **in the resource-loading helper only** and note it.
4. `build.ps1`: `uv sync --frozen`, `uv run pyinstaller --noconfirm
   --clean packaging/word-session.spec`, copy `packaging/shims/*.cmd` into
   `dist/WordSession/`, then zip `dist/WordSession` to
   `dist/WordSession-<version>-win64.zip`.
5. Shims (CRLF line endings per `.gitattributes`), each calling the exe in
   the same folder (`"%~dp0word-session.exe"`):
   - `WriteSession` → `save`;
   - `LoadSession "%~1"` → `restore` with the argument if given (file path
     selector) else `latest`;
   - `GetDocuments` → `current`;
   each followed by `if errorlevel 1 pause` like the originals.
6. `smoke_test.ps1 -Dist dist\WordSession`: with a temp `WORD_SESSION_HOME`
   run `word-session.exe --version`, `word-session.exe --demo --json
   doctor` (parse JSON), `word-session.exe --demo save`, `--demo list`;
   start `word-session.exe --demo serve --port 0` as a background process,
   read the URL from its stdout, GET `/api/health`, stop it. Non-zero exit
   on any failure.
7. CI: after tests, run `packaging/build.ps1` and `smoke_test.ps1`, upload
   the zip as an artifact.

## Acceptance

```text
powershell -ExecutionPolicy Bypass -File packaging/build.ps1
powershell -ExecutionPolicy Bypass -File packaging/smoke_test.ps1 -Dist dist\WordSession
```

Both succeed. Report the bundle size (`du -sh dist/WordSession`), zip
size, and cold start time of `word-session.exe --version` (three runs).
Manually: double-click `word-session-app.exe` → tray icon + manager in the
browser (with `--demo` passed via a shortcut is fine).
