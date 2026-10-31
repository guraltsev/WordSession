# Job 12 — CLI core commands

Depends on: 11
Plan reference: §3.7
Decisions: D6 (argparse)

## Goal

Replace the stub CLI with the real command-line interface for the everyday
commands — `save`, `restore` (alias `load`), `current`, `list`, `show` —
with stable exit codes and machine-readable output.

## Files

- `src/word_session/cli.py` (replace the stub; keep `main`/`app_main` names)
- `tests/cli/__init__.py`, `tests/cli/test_cli_core.py`
- `tests/unit/test_smoke.py` (adjust only if the stub behaviour it tests changed)

## Contract

```python
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_WORD_UNAVAILABLE = 3
EXIT_PARTIAL_RESTORE = 4
EXIT_NOT_FOUND = 5
EXIT_NOT_RESPONDING = 6

def main(argv: list[str] | None = None, *,
         service_factory: Callable[[argparse.Namespace], SessionService] | None = None) -> int: ...
def app_main() -> None: ...
```

`service_factory` is for tests; default builds the service with
`open_service(settings=..., fake=args.demo)` (see global options) and always
calls `service.close()` afterwards.

## Command line

```text
word-session [global options] <command> [command options]

global:
  --version
  --json                 machine-readable output on stdout
  -v / --verbose         console log level DEBUG and tracebacks on errors
  -q / --quiet           only errors on stderr
  --config PATH          settings file (default: app_paths().config_file)
  --sessions-dir DIR     override settings.sessions_dir for this run
  --demo                 use the fake Word backend (for trying the tool)

save     [--name NAME]
restore  [SELECTOR] [--only GLOB ...] [--no-start] [--no-position] [--dry-run]
load     (alias of restore; same options)
current
list     [--limit N] [--kind manual|auto|imported]
show     SELECTOR
```

`SELECTOR` defaults to `latest` for `restore`/`load`.

## Behaviour

- Logging: `configure_logging(paths.log_dir, console_level=...)` with
  WARNING by default, DEBUG with `-v`, ERROR with `-q`.
- Human output (stdout), concise, examples (exact spacing free):
  - `save`: `Saved "Session 2026-01-02 03:04" (2 documents) → <path>` then
    warnings prefixed `warning: ` on stderr.
  - `restore`: one line per result `opened      C:\Docs\a.docx`,
    `missing     C:\Docs\old.docx`, … then a summary `3 opened, 1 missing`.
  - `current`: one line per document: `* ` marker for the active one, path,
    `p. 12, l. 7` when known.
  - `list`: columns id, kind, docs count, name; newest first; `--limit`
    default 20; pinned sessions marked `[pinned]` (ASCII only; the Windows
    console may not render emoji).
  - `show`: header (name, id, kind, created, host, notes) then documents
    with location and an `exists`/`MISSING` flag for local/unc paths.
- `--json`: print exactly one JSON document to stdout:
  - `save` → `{"session": <Session>, "warnings": [...], "path": "..."|null}`
  - `restore` → `<RestoreReport>`
  - `current` → `[<DocumentState>, ...]`
  - `list` → `[<Session>, ...]`; `show` → `<Session>`
  - errors → `{"error": {"type": "<ExceptionClass>", "message": "..."}}` on
    stdout as well, with the same exit code.
- Exit codes:
  - `WordUnavailable` → 3 (message: "Word is not running" + hint "start
    Word or omit --no-start" when relevant);
  - restore report not `ok` → 4;
  - `SessionNotFound`/`AmbiguousSelector` → 5 (list candidates for
    ambiguity);
  - `WordNotResponding` → 6;
  - `ConfigError`, `StoreError`, `ServiceError`, `WordError` → 1 with a
    one-line message; full traceback logged (and printed with `-v`);
  - argparse usage errors → 2; unexpected exceptions → 1, traceback to
    the log, one line "unexpected error, see <log path>" on stderr.
- `save` with no open documents: message "Word has no open documents;
  nothing saved", exit 0 (it is not an error).
- `main` never calls `sys.exit` itself; `__main__.py` and the console
  script do.

## Tests (`tests/cli/test_cli_core.py`)

Use `service_factory` returning the `service` fixture from job 11 (with its
fake backend), `capsys` for output. At least:

- every command in human and `--json` mode (parse the JSON);
- `load` behaves as `restore`;
- default selector `latest`; `--only`, `--no-start` (fake not running →
  exit 3), `--no-position` (no `restore_position` in `fake_backend.calls`),
  `--dry-run`;
- each exit code path, including partial restore (a `missing` document)
  and ambiguous selector;
- `--sessions-dir` override is honoured (use the default factory with
  `--demo` and `WORD_SESSION_HOME`);
- `--version`, no command → usage exit 2;
- `-q` suppresses non-error output.

## Acceptance

README rule 7 commands, plus a manual run in the demo backend:

```text
uv run word-session --demo save --name "demo"
uv run word-session --demo list
uv run word-session --demo restore --dry-run
uv run word-session --demo --json show latest
```

(with `WORD_SESSION_HOME` set to a temp dir in the shell first).
