# Job 12 report
Status: done

## Changed files
- `src/word_session/cli.py` (replaced stub)
- `tests/cli/__init__.py`, `tests/cli/test_cli_core.py` (new, 29 tests)
- `tests/unit/test_smoke.py` unchanged (still passes).

## What was done
Argparse CLI with global options (`--version --json -v -q --config --sessions-dir --demo`) and commands `save`, `restore`/`load`, `current`, `list`, `show`. Exit codes 0-6 as specified, `service_factory` hook, service always closed, JSON output and JSON error documents, logging via `configure_logging`.

## Acceptance results
- `ruff format --check .`: 37 files already formatted
- `ruff check .`: All checks passed
- `pyright`: 0 errors, 0 warnings
- `pytest`: 174 passed, 30 skipped
- Manual demo run (temp `WORD_SESSION_HOME`): save, list, restore --dry-run, `--json show latest`, `--json current` all worked, exit 0.

## Deviations from the job text (and why)
- `save` prints `->` instead of the Unicode arrow, since Windows consoles may not encode it. `main` also sets stdout/stderr `errors="replace"` when the stream supports `reconfigure`.
- `-q` suppresses all human stdout (including `list`/`show` output) and warnings; errors still print. `--json` output is unaffected by `-q`.
- No-command usage help is printed to stdout (the existing smoke test requires this); argparse usage errors go to stderr.
- Failures are logged at DEBUG (with traceback) to the file log, so the console does not repeat the message; with `-v` the DEBUG console handler prints the traceback.
- Global options must come before the command (argparse subparser behaviour).
- `show` checks existence with `Path.exists()` locally; with `--demo` all local/unc paths are shown as `exists`.
- `list --limit` of a negative value yields an empty list.
- `app_main` still calls `main(["app"])` (stub kept from before; `app` command is not part of this job, so it currently gives exit 2).

## Out-of-scope findings
None.

## For final human testing
1. In a console with real Word running and documents open: `uv run word-session save`, then close the documents and `uv run word-session restore`. Expected: documents reopen, exit code 0, cursors restored.
2. `uv run word-session current` with Word closed. Expected: `error: Word is not running`, exit code 3.

## Notes for the coordinator
Whole-repo checks passed including the other executors' in-progress files at the time of running.
