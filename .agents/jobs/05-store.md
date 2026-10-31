# Job 05 — Session store

Depends on: 04
Plan reference: §3.3 (decisions list), §3.6 (selectors)

## Goal

Persist sessions as files safely: atomic writes, deterministic ordering,
selector lookup, recoverable deletion and retention pruning — with no Word
dependency.

## Files

- `src/word_session/store.py`
- `tests/unit/test_store.py`

## Contract

```python
class StoreError(Exception): ...
class SessionNotFound(StoreError): ...
class AmbiguousSelector(StoreError):
    candidates: list[str]           # session ids

class SessionStore:
    def __init__(self, root: Path) -> None: ...
    root: Path                      # sessions dir; created on first write
    trash_dir: Path                 # root / "trash"

    def new_id(self, created_at: datetime, name: str) -> str: ...
    def save(self, session: Session) -> Path: ...
    def load_file(self, path: Path) -> Session: ...
    def list(self) -> list[Session]: ...            # newest first
    def list_invalid(self) -> list[tuple[Path, str]]: ...
    def get(self, selector: str) -> Session: ...
    def path_for(self, session_id: str) -> Path: ...
    def revision(self, session_id: str) -> str: ...
    def delete(self, session_id: str, *, purge: bool = False) -> None: ...
    def prune(self, keep: int) -> list[str]: ...    # returns removed ids
```

## Behaviour

- File name: `<id>.json` in `root`. Encoding UTF-8, `\n` newlines,
  `indent=2`, `ensure_ascii=False`, trailing newline.
- `save`: write to `<id>.json.tmp` in the same dir, `flush` + `os.fsync`,
  then `os.replace`. On any exception remove the temp file and re-raise.
  Overwrites an existing file with the same id (that is how rename/pin work).
- `new_id`: `make_session_id(...)`; if `<id>.json` exists in root or trash,
  append `-2`, `-3`, … until free.
- `load_file`: reads and validates a **v1** file; raises `StoreError` with
  the path and the reason for invalid JSON / validation errors. (Legacy
  formats are job 06; do not handle them here.)
- `list`: every `*.json` directly in `root` (not `trash/`, not `*.tmp`),
  sorted by id descending (ids start with a timestamp, so this is newest
  first). Invalid files are skipped and logged with `logging.getLogger(__name__).warning`;
  `list_invalid` returns them with the error text.
- `get(selector)` resolution order — first rule that matches wins:
  1. `"latest"` → newest; `"latest-manual"`/`"latest-auto"` → newest of that kind;
  2. `-N` (N ≥ 1) → N-th newest (`-1` = newest);
  3. an existing file path (absolute or relative to cwd) ending in `.json` → `load_file`;
  4. exact id;
  5. exact name (case-insensitive); several → `AmbiguousSelector`;
  6. unique id prefix (≥ 4 chars); several → `AmbiguousSelector`;
  otherwise `SessionNotFound` whose message names the selector.
  Empty store → `SessionNotFound("no sessions in <root>")`.
- `revision`: SHA-256 hex of the file bytes (used later as HTTP ETag).
- `delete`: move the file into `trash_dir` (create it); if a file with that
  name exists in trash, overwrite it. `purge=True` deletes outright. Unknown
  id → `SessionNotFound`.
- `prune(keep)`: among sessions with `kind == "auto"` and `pinned is False`,
  keep the newest `keep`, move the rest to trash; return their ids. Manual,
  imported and pinned sessions are never pruned. `keep < 0` → `ValueError`.

## Tests (at least)

- save/load round-trip; file is UTF-8 with non-ASCII path text intact;
- atomicity: monkeypatch `os.replace` to raise → original file unchanged,
  no `.tmp` left;
- `new_id` collision suffixes, including a collision with a trashed file;
- ordering; `.tmp`, non-JSON and `trash/` files ignored; invalid file
  skipped and reported by `list_invalid`;
- every selector rule, ambiguity for names and prefixes, not-found messages,
  empty store;
- `revision` changes when content changes;
- delete to trash, purge, unknown id;
- prune keeps manual/imported/pinned, honours `keep`, `keep=0`, negative.

Use `Session` objects built in a small local factory in the test module
(e.g. `def make_session(**overrides)`); fixed aware datetimes.

## Acceptance

README rule 7 commands.
