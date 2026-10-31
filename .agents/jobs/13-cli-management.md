# Job 13 — CLI management commands, first-run import, doctor

Depends on: 12
Plan reference: §3.7, §3.4 (first-run import), §3.10 (doctor)

## Goal

Complete the CLI with session management, legacy import (including the
automatic first-run import) and a `doctor` command that explains why Word
cannot be reached.

## Files

- `src/word_session/cli.py` (add commands)
- `src/word_session/service.py` (add `first_run_import` only)
- `src/word_session/doctor.py` (new)
- `tests/cli/test_cli_management.py`, `tests/unit/test_doctor.py`,
  `tests/unit/test_first_run_import.py`

## Commands

```text
rename        SELECTOR NEW_NAME
delete        SELECTOR [--purge] [--yes]
pin           SELECTOR
unpin         SELECTOR
notes         SELECTOR TEXT
prune         [--keep N]
diff          SELECTOR_A SELECTOR_B
import-legacy [DIR ...]
doctor
```

- `rename/pin/unpin/notes` → `service.update(...)`; print the updated
  session line; `--json` prints the session.
- `delete`: without `--yes` and when stdin is a TTY, ask
  `Delete "<name>" (<id>)? [y/N]`; non-TTY without `--yes` → exit 2 with
  "use --yes". `--purge` deletes permanently, otherwise moves to trash and
  says where.
- `prune` prints removed ids; `--json` → `{"removed": [...]}`.
- `diff` prints `+ path` / `- path`; `--json` → `SessionDiff` as dict.
- `import-legacy` prints counts and errors; `--json` → summary dict
  (paths as strings).
- `doctor`: prints one line per check: `ok`, `warn` or `FAIL`, name,
  detail; exit 0 if no `FAIL`, else 1. `--json` → list of checks.

## Contract — `doctor.py`

```python
@dataclass
class Check:
    name: str
    status: Literal["ok", "warn", "fail"]
    detail: str

def run_checks(service: SessionService, paths: AppPaths) -> list[Check]: ...
```

Checks, in order (each wrapped so one failing check never stops the rest;
an exception becomes `fail` with the message):

1. `python` — version and executable (always ok);
2. `pywin32` — importable and version (`fail` on Windows if missing; `warn`
   elsewhere);
3. `word-installed` — on Windows, registry key
   `HKEY_CLASSES_ROOT\Word.Application\CLSID` exists (`winreg`, guarded
   import);
4. `word-running` — `service.word_info().running` (warn if not);
5. `word-process` — `tasklist /FI "IMAGENAME eq WINWORD.EXE" /NH` shows a
   process; if a process exists but check 4 says not running → `fail` with
   "Word is running but not reachable over COM. This usually means Word and
   word-session run at different privilege levels (one as administrator)."
6. `elevated` — `ctypes.windll.shell32.IsUserAnAdmin()` (warn if elevated);
7. `sessions-dir` — exists or creatable, writable (create and delete a temp
   file), number of sessions, number of invalid files (`warn` if > 0);
8. `config` — `load_settings` succeeds;
9. `log` — log file path;
10. `legacy` — legacy dirs found and whether the first-run import marker
    exists.

Inject the probes for tests: `run_checks` takes optional keyword args
`tasklist: Callable[[], str] | None`, `is_admin: Callable[[], bool] | None`,
`word_registered: Callable[[], bool] | None` with real defaults.

## Contract — first-run import (`service.py`)

```python
def first_run_import(service: SessionService, paths: AppPaths) -> ImportSummary | None: ...
```

If `paths.data_dir / ".legacy-imported"` exists → `None`. Else run
`service.import_legacy()`, write the marker (UTF-8 text: ISO timestamp and
counts), return the summary. Errors in individual files do not prevent the
marker. The CLI calls it before every command except `doctor`,
`import-legacy` and `--version`, and prints
`Imported N sessions from the old word-session tools.` on stderr when N > 0.

## Tests

- every command human + `--json`, delete confirmation paths (monkeypatch
  `sys.stdin.isatty` and `input`), non-TTY without `--yes`;
- doctor: each check with injected probes, including the "running but not
  reachable" fail and an exception inside one check;
- first-run import: runs once, marker written, second call `None`, errors
  still write the marker; CLI prints the message once.

## Acceptance

README rule 7 commands; `uv run word-session --demo doctor` prints all ten
checks (use a temp `WORD_SESSION_HOME`).
