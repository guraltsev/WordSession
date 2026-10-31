# Job 08 — Word backend protocol, constants and fake

Depends on: 04
Plan reference: §3.5 (protocol, `FakeWordBackend`), §4 (contract tests)

## Goal

Define the single interface through which the app talks to Word, and a
scriptable in-memory fake that every non-Word test (service, CLI, API, UI)
will use.

## Files

- `src/word_session/word/__init__.py` (re-exports the public names below)
- `src/word_session/word/backend.py`
- `src/word_session/word/constants.py`
- `src/word_session/word/fake.py`
- `tests/contract/__init__.py`, `tests/contract/conftest.py`,
  `tests/contract/test_backend_contract.py`
- `tests/unit/test_fake_backend.py`

## Contract — `backend.py`

```python
class WordError(Exception): ...
class WordUnavailable(WordError): ...     # not running and may not start / not installed
class WordNotResponding(WordError): ...   # a call exceeded its timeout (raised by worker)
class WordBusy(WordError): ...            # Word rejected the call; retry later
class DocumentMissing(WordError): ...
class DocumentLocked(WordError): ...

OpenOutcome = Literal["opened", "already_open"]

class WordInfo(BaseModel):
    running: bool
    version: str = ""
    visible: bool = False
    document_count: int = 0

class WordBackend(Protocol):
    def is_running(self) -> bool: ...
    def connect(self, *, start_if_needed: bool) -> None: ...
    def info(self) -> WordInfo: ...
    def list_documents(self) -> list[DocumentState]: ...
    def open_document(self, doc: DocumentState, *, read_only: bool = False) -> OpenOutcome: ...
    def restore_position(self, doc: DocumentState) -> None: ...
    def activate(self, path: str) -> None: ...
    def disconnect(self) -> None: ...
```

Semantics (document them in the Protocol's docstrings — this text is the
contract the COM backend must also satisfy):

- `is_running`: cheap check, never starts Word, never raises for "not
  running".
- `connect(start_if_needed=False)` when Word is not running →
  `WordUnavailable`. `start_if_needed=True` starts it (visible). Idempotent.
- Every other method except `is_running`/`disconnect` requires `connect`
  first; otherwise `WordError("not connected")`.
- `info()` works when not connected only for `running` (others defaults);
  when connected returns real values.
- `list_documents()`: one `DocumentState` per open document, in Word's
  collection order, exactly one with `active=True` if any documents are
  open; **must not change which document is active**.
- `open_document`: path compared case-insensitively against open documents
  → `"already_open"` (no reopen). Missing file → `DocumentMissing`; file
  locked by another process → `DocumentLocked`; other failures →
  `WordError` with Word's message. Never shows a modal dialog.
- `restore_position(doc)`: document must be open (else `WordError`); uses
  `position.start/end` clamped to the document length when present, else
  page/line, else does nothing. Does not raise for out-of-range positions.
- `activate(path)`: brings that open document to the front.
- `disconnect()`: drops references; never raises; Word keeps running.

## Contract — `constants.py`

Module-level integer constants, each with a short comment, values from the
Word object model: `wdActiveEndPageNumber = 3`, `wdFirstCharacterLineNumber = 10`,
`wdGoToPage = 1`, `wdGoToLine = 3`, `wdGoToAbsolute = 1`, `wdGoToRelative = 2`,
`wdAlertsNone = 0`, `wdAlertsAll = -1`, `wdWindowStateNormal = 0`,
`wdWindowStateMaximize = 1`, `wdWindowStateMinimize = 2`,
`wdDoNotSaveChanges = 0`. Plus HRESULTs: `RPC_E_CALL_REJECTED = -2147418111`,
`RPC_E_SERVERCALL_RETRYLATER = -2147417846`, `MK_E_UNAVAILABLE = -2147221021`
(`GetActiveObject` "not running").

## Contract — `fake.py`

```python
@dataclass
class FakeDocument:
    path: str
    length: int = 10_000
    position: Position = field(default_factory=Position)
    read_only: bool = False
    saved: bool = True

class FakeWordBackend:      # implements WordBackend
    def __init__(self, *, running: bool = True, installed: bool = True,
                 documents: list[FakeDocument] | None = None,
                 existing_paths: set[str] | None = None,   # None = every path exists
                 locked_paths: set[str] | None = None,
                 version: str = "16.0") -> None: ...
    # scripting knobs (public attributes)
    busy_calls: int                     # next N calls raise WordBusy
    fail_paths: dict[str, Exception]    # open_document(path) raises this
    hang: threading.Event | None        # not None: every call waits for the event (see below)
    calls: list[str]                    # method names in call order
    active_index: int | None            # index of active document
```

- `hang`: when not `None`, each call waits on `hang.wait()` before doing
  anything (tests set it later to release). Keep it simple.
- Starting via `connect(start_if_needed=True)` sets `running=True` unless
  `installed=False` → `WordUnavailable`.
- `open_document` appends a `FakeDocument`, makes it active, honours
  `existing_paths`, `locked_paths`, `fail_paths`.
- `restore_position` stores the clamped position on the fake document.
- Thread-safe enough for the worker tests: guard state with a `Lock`.

## Contract tests

`tests/contract/conftest.py` defines a fixture `backend_factory`
parametrised over `["fake", "com"]`. The `"com"` param is marked `word` and,
when run, imports `ComWordBackend` (job 09) — for now it calls
`pytest.skip("COM backend not implemented yet")` if the import fails.
Each contract test receives a *connected backend with documents A and B
open, B active* via a fixture that, for `"fake"`, constructs it directly and,
for `"com"`, is filled in by job 09 (leave a clearly marked `TODO(job 09)`
branch that skips).

`test_backend_contract.py` covers every semantic bullet above that can be
expressed generically: not-running/connect, not-connected errors,
list order + single active + active unchanged after listing, open already
open (case-insensitive), open missing, restore position clamping, activate,
disconnect idempotent.

`test_fake_backend.py` covers fake-only knobs: `busy_calls`, `fail_paths`,
`hang`, `calls` log, `installed=False`.

## Acceptance

README rule 7 commands; `pytest tests/contract` shows fake params passing
and com params skipped.
