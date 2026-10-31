# Testing policy

Tooling: `pytest`, `pytest-cov`, `ruff` (lint and format), `pyright` on
`src/`.

## Test levels

| Level | What | Needs Word | Runs in CI |
| --- | --- | --- | --- |
| Unit | Model validation, store (atomic write, sort, prune, trash, corrupt-file tolerance), legacy readers, selectors, config, service logic with `FakeWordBackend` and a fake clock | no | yes |
| Contract | One parametrised suite asserting `WordBackend` behaviour; runs against `FakeWordBackend` always and `ComWordBackend` when Word is available | optional | fake only |
| Worker | `ComWorker` timeouts, retry on simulated busy HRESULTs, error propagation, shutdown | no | yes |
| CLI | `main([...])` with `capsys`, exit codes, `--json` output snapshots | no | yes |
| API | `TestClient`: auth, token and Host checks, endpoints, job lifecycle, SSE | no | yes |
| UI | Playwright against `serve --demo` (fake backend): list, detail, partial restore, settings | no | optional nightly |
| Integration | Real Word: generate `.docx` fixtures in `tmp_path` via COM, capture, close, restore, assert positions; missing, locked, unsaved and already-open documents | yes | no; marked `word` |
| Packaging smoke | Built executable: `--version`, `doctor --json`, `serve --demo` responds | no | yes (Windows runner) |

Fixtures for legacy formats live in `tests/fixtures/legacy/`: a Python v0
file, a UTF-16 PowerShell file, a PowerShell file with a single document, a
truncated or corrupt file, and a file with non-ASCII paths.

## Rules

- Give every new behaviour tests in `tests/`.
- Never let a test touch the real home directory, `%APPDATA%`,
  `%LOCALAPPDATA%` or a running Word. Set `WORD_SESSION_HOME` to a `tmp_path`
  (fixture `isolated_home` in `tests/conftest.py`) and use `FakeWordBackend`.
- Mark tests that drive real Word with `@pytest.mark.word`. They are skipped
  unless `WORD_SESSION_TEST_WORD=1`. They must use isolated Word processes
  (`DispatchEx`) and leave none behind.
- Mark tests that attach to a Word instance the user left running with
  `@pytest.mark.shared_word` (enabled by `WORD_SESSION_TEST_SHARED_WORD=1`).
  They may open and close only documents they created in a temp folder, must
  restore the previously active document, and must never call `Quit`, close
  other documents or change options.
- Keep tests deterministic: inject clocks and backends; do not sleep for real
  time.

## Coverage

- At least 90 % for `model`, `store`, `legacy`, `service`, `cli` and `web`.
- The COM module is covered by the integration suite only.

## Commands

Run all four before declaring work done; all must pass:

```text
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
```

Run Word integration tests on a Windows machine with Word installed:

```text
set WORD_SESSION_TEST_WORD=1
uv run pytest -m word
```

Run the browser UI tests (Playwright, demo backend; skipped unless enabled):

```text
uv run playwright install chromium
set WORD_SESSION_TEST_UI=1
uv run pytest -m ui
```

The UI tests start the server in-process on a free port with the fake Word
backend and a temporary `WORD_SESSION_HOME`; no real Word is involved.

## CI

GitHub Actions on `windows-latest`: `uv sync --frozen`, ruff, type check,
pytest (without the `word` marker), PyInstaller build, smoke test, artifact
upload.
