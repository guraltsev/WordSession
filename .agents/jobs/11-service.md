# Job 11 — Session service

Depends on: 05, 06, 07, 10
Plan reference: §3.6

## Goal

Implement the use cases (capture, restore with a per-document report,
listing, editing, deleting, pruning, legacy import, autosave tick) once, so
the CLI, tray and web API are thin wrappers.

## Files

- `src/word_session/events.py`
- `src/word_session/service.py`
- `tests/unit/test_events.py`, `tests/unit/test_service.py`
- `tests/conftest.py` (add shared fixtures below; do not remove existing ones)

## Contract — `events.py`

```python
Event = dict[str, Any]          # always has "type"

class EventBus:
    def subscribe(self, callback: Callable[[Event], None]) -> Callable[[], None]: ...  # returns unsubscribe
    def publish(self, event: Event) -> None: ...
```

Callbacks run synchronously on the publishing thread; an exception in one
callback is logged and does not stop the others. Thread-safe subscribe/
unsubscribe.

Event types used by the service (exact keys):

| type | extra keys |
| --- | --- |
| `session_saved` | `session_id`, `kind` |
| `session_updated` | `session_id` |
| `session_deleted` | `session_id` |
| `restore_started` | `session_id`, `total` |
| `restore_progress` | `session_id`, `result` (RestoreResult as JSON dict), `index`, `total` |
| `restore_finished` | `session_id`, `report` (RestoreReport as JSON dict) |
| `autosave_failed` | `message` |

## Contract — `service.py`

```python
class ServiceError(Exception): ...
class RevisionConflict(ServiceError): ...
class RestoreInProgress(ServiceError): ...

@dataclass
class CaptureResult:
    session: Session
    warnings: list[str]
    path: Path | None           # None when nothing was saved

@dataclass
class SessionDiff:
    added: list[str]            # paths in b not in a (case-insensitive)
    removed: list[str]

class SessionService:
    def __init__(self, store: SessionStore, worker: ComWorker, settings: Settings, *,
                 events: EventBus | None = None,
                 clock: Callable[[], datetime] | None = None,     # default: aware now()
                 host: str | None = None,                         # default: socket.gethostname()
                 path_exists: Callable[[str], bool] | None = None # default: os.path.exists
                 ) -> None: ...
    events: EventBus
    settings: Settings
    store: SessionStore
    @property
    def restore_in_progress(self) -> bool: ...

    def word_info(self) -> WordInfo: ...
    def current(self) -> list[DocumentState]: ...
    def capture(self, name: str | None = None, *, kind: SessionKind = "manual") -> CaptureResult: ...
    def restore(self, selector: str, *, only: list[str] | None = None,
                start_word: bool | None = None, restore_position: bool | None = None,
                dry_run: bool = False,
                progress: Callable[[RestoreResult], None] | None = None) -> RestoreReport: ...
    def list_sessions(self, *, kind: SessionKind | None = None) -> list[Session]: ...
    def get(self, selector: str) -> Session: ...
    def revision(self, selector: str) -> str: ...
    def update(self, selector: str, *, expected_revision: str | None = None,
               name: str | None = None, pinned: bool | None = None,
               notes: str | None = None, remove_paths: list[str] | None = None) -> Session: ...
    def delete(self, selector: str, *, purge: bool = False) -> None: ...
    def prune(self, keep: int | None = None) -> list[str]: ...
    def import_legacy(self, dirs: list[Path] | None = None) -> ImportSummary: ...
    def diff(self, a: str, b: str) -> SessionDiff: ...
    def autosave_tick(self) -> Session | None: ...
    def close(self) -> None: ...                 # stops the worker

def open_service(*, settings: Settings | None = None, fake: bool = False) -> SessionService: ...
```

## Behaviour

- `word_info`: `worker.call(lambda b: b.info())`; does not connect.
- `current`: `connect(start_if_needed=False)` then `list_documents()` in one
  worker call. `WordUnavailable` propagates.
- `capture`:
  - documents from `current()`;
  - default name: manual `"Session YYYY-MM-DD HH:MM"`, auto
    `"Autosave YYYY-MM-DD HH:MM"` (from `clock()`);
  - warnings (exact wording is free, content is not): one per `unsaved`
    document ("never saved, cannot be restored"), one per document with
    `had_unsaved_changes` ("unsaved changes are not part of the session"),
    and "Word has no open documents" when empty;
  - empty → nothing saved (`path=None`); else `store.new_id`, `host`,
    `word_version` from `word_info()`, `store.save`, publish
    `session_saved`.
- `restore`:
  - only one restore at a time (`RestoreInProgress`); flag cleared in
    `finally`;
  - `start_word`/`restore_position` default to `settings.restore.*`;
  - `only`: keep documents whose full path or file name matches any glob
    (`fnmatch`, case-insensitive);
  - order: documents with `active=False` first (session order), the active
    one last;
  - `unsaved` → `skipped`; `local`/`unc` and `not path_exists(path)` →
    `missing` (no Word call);
  - `dry_run`: no Word calls at all; every remaining document gets
    `skipped` with message `"dry run: would open"`;
  - otherwise one `connect(start_if_needed=start_word)` first
    (`WordUnavailable` propagates and nothing is reported as attempted);
    then per document one worker call doing `open_document` and, if
    requested, `restore_position` (position failure keeps the open status
    and sets `message="position not restored: …"`);
    `DocumentMissing` → `missing`, `DocumentLocked` → `locked`,
    `WordNotResponding`/`WordBusy`/`WordError` → `failed` with the message;
    never abort the loop;
  - finally `activate` the last successfully opened document (ignore
    errors);
  - publish `restore_started`, one `restore_progress` per document (also
    call `progress`), `restore_finished`.
- `update`: if `expected_revision` is given and differs from
  `store.revision(id)` → `RevisionConflict`. Changes only the given fields;
  `remove_paths` removes matching documents (case-insensitive). The id never
  changes. Saves, publishes `session_updated`, returns the new session.
- `delete` → store, publish `session_deleted`. `prune` default keep
  `settings.autosave.keep`. `import_legacy` default dirs
  `legacy.default_legacy_dirs()`.
- `autosave_tick`: return `None` without side effects if a restore is in
  progress, or `word_info().running` is false (never start Word), or Word
  has no documents, or (`settings.autosave.only_on_change` and the newest
  `auto` session has the same `fingerprint()`). Otherwise capture with
  `kind="auto"`, then `prune()`, return the session. Any `WordError` →
  publish `autosave_failed` and return `None` (do not raise).
- `open_service`: settings default `load_settings()`; paths via
  `app_paths()`/`resolve_sessions_dir`; `fake=True` uses a
  `FakeWordBackend` with three demo documents under `C:\Demo\` and
  `path_exists=lambda p: True`; otherwise `ComWordBackend()`; worker
  `call_timeout = settings.restore.open_timeout_s`; worker started.

## Shared test fixtures (add to `tests/conftest.py`)

- `fake_backend` → `FakeWordBackend` with docs `C:\Docs\a.docx`,
  `C:\Docs\b.docx` (b active);
- `worker(fake_backend)` → started `ComWorker(lambda: fake_backend,
  call_timeout=2)`, stopped at teardown;
- `fixed_clock` → callable returning successive aware datetimes one minute
  apart, starting `2026-01-02 03:04:05+00:00`;
- `service(worker, isolated_home, fixed_clock)` → `SessionService` with a
  store in `isolated_home / "sessions"`, default `Settings()`,
  `path_exists` returning `True` unless the path contains `missing`.

## Tests (at least)

Every bullet above, including: warnings content; empty capture saves
nothing; restore order and active last; `only` globs; each status mapping;
position failure message; `WordUnavailable` before any document; dry run
makes zero backend calls (check `fake_backend.calls`); events published in
order with the right keys; `RestoreInProgress` (start a restore blocked on
`hang` in a thread, then try another); `update` with stale revision;
autosave skip conditions and prune; `autosave_failed` on error.

## Acceptance

README rule 7 commands.
