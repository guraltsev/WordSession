# Development guide

## Prerequisites

- Windows 10 or 11 (the Word backend uses COM; the rest of the code also
  imports on Linux and macOS).
- Microsoft Word, only needed for real-Word integration tests and manual use.
- [`uv`](https://docs.astral.sh/uv/) for Python and dependency management.

## Setup (available after job 02)

```text
uv sync
```

## Checks and tests (available after job 02)

```text
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
```

See `docs/tests.md` for the testing policy. Follow `docs/python_rules.md` for
code style and `docs/docstring_schema.md` for docstrings.

## Word integration tests (available after job 02)

Run on a Windows machine with Word. These tests use isolated Word processes
and are skipped by default:

```text
set WORD_SESSION_TEST_WORD=1
uv run pytest -m word
```

## Building the Windows bundle

```text
powershell -ExecutionPolicy Bypass -File packaging/build.ps1
powershell -ExecutionPolicy Bypass -File packaging/smoke_test.ps1 -Dist dist\WordSession
```

`build.ps1` runs `uv sync --frozen`, PyInstaller with `packaging/word-session.spec`
(onedir: console `word-session.exe` and windowed `word-session-app.exe` in one
`dist\WordSession` folder), copies the legacy `.cmd` shims from
`packaging/shims/` next to the executables, and zips the folder to
`dist\WordSession-<version>-win64.zip`. Pass `-NoSync` to skip `uv sync` (for
example when an executable in `.venv` is locked by a running process).
`smoke_test.ps1` exercises the built executable against the fake Word backend
(`--version`, `doctor`, `save`, `list`, and `serve` with a health request;
`-SkipServe` omits the last). Both are also run by CI, which uploads the zip.

## Where data lives

Paths come from `platformdirs` (available after job 03). `WORD_SESSION_HOME`
overrides all of them and is used by tests.

| What | Location |
| --- | --- |
| Sessions | `%APPDATA%\word-session\sessions\` |
| Config | `%APPDATA%\word-session\config.toml` |
| Logs | `%LOCALAPPDATA%\word-session\logs\word-session.log` (rotating, 5 x 1 MB) |
| Instance info | `%LOCALAPPDATA%\word-session\instance.json` (port, token, pid) |

## Project layout

Modules appear as the migration jobs land (see `docs/migration_plan.md`).

```text
pyproject.toml              # uv-managed (job 02)
src/word_session/
    model.py                # Session, DocumentState, RestoreResult/Report
    store.py                # SessionStore: list/load/save/delete/rename/prune
    legacy.py               # readers for Python-v0 and PowerShell files
    config.py               # Settings (TOML) + platform paths
    service.py              # SessionService (use cases)
    logging_setup.py        # rotating file log + console handler
    word/                   # backend protocol, COM backend, worker, fake
    cli.py                  # argparse subcommands
    web/                    # HTTP API + static UI
    tray.py                 # pystray icon + menu
    instance.py             # single-instance mutex + instance.json
    autostart.py            # HKCU Run toggle
tests/                      # unit, contract, cli, api, ui, integration
packaging/                  # PyInstaller spec, optional installer, icons
docs/                       # policies, guides, migration plan
legacy/                     # old scripts, read-only reference
```
