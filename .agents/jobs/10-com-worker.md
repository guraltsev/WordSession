# Job 10 — COM worker

Depends on: 08
Plan reference: §3.5 rules 4, 5; §2 "never hang a front end"

## Goal

Run every Word call on one dedicated COM thread, with caller-side timeouts
and automatic retry when Word is busy, so a stuck Word can never freeze the
CLI, tray or web server.

## Files

- `src/word_session/word/worker.py`
- `tests/unit/test_worker.py`

## Contract

```python
T = TypeVar("T")

class ComWorker:
    def __init__(self, backend_factory: Callable[[], WordBackend], *,
                 call_timeout: float = 30.0,
                 busy_retry_total: float = 10.0) -> None: ...
    def start(self) -> None: ...
    def stop(self, timeout: float = 5.0) -> None: ...
    def submit(self, fn: Callable[[WordBackend], T]) -> Future[T]: ...
    def call(self, fn: Callable[[WordBackend], T], *, timeout: float | None = None) -> T: ...
    @property
    def is_stuck(self) -> bool: ...
    def __enter__(self) -> "ComWorker": ...   # start()
    def __exit__(self, *exc) -> None: ...     # stop()
```

## Behaviour

- `start` launches one daemon thread named `"word-com"`. On that thread:
  if `pythoncom` imports, call `pythoncom.CoInitialize()` (and
  `CoUninitialize()` on exit); then create the backend by calling
  `backend_factory()` **on the worker thread** (COM objects belong to the
  thread that created them). `start` twice → `RuntimeError`.
- Jobs run strictly one at a time, in submission order.
- **Busy retry** (inside the worker): if `fn` raises `WordBusy`, sleep and
  retry with delays `0.1, 0.25, 0.5, 1, 2, 2, 2, …` seconds until the total
  sleep would exceed `busy_retry_total`, then let the last `WordBusy`
  propagate. Log each retry at DEBUG. Other exceptions propagate
  immediately through the future.
- **Timeout** (`call`): wait on the future for `timeout` (default
  `call_timeout`). On expiry raise `WordNotResponding("Word did not respond
  within N s; it may be showing a dialog")`. The job keeps running on the
  worker; the future is not cancelled.
- `is_stuck` is `True` while the currently running job has been running
  longer than `call_timeout`. While stuck, `call` and `submit` fail fast
  with `WordNotResponding` instead of queueing. When the job finally
  returns, the worker is no longer stuck.
- Re-entrancy: `call`/`submit` from the worker thread itself run `fn`
  directly (no deadlock).
- `stop`: enqueue a sentinel, wait up to `timeout` for the thread; pending
  (not started) futures get `WordError("worker stopped")`; the backend's
  `disconnect()` runs on the worker thread before it exits. Calling methods
  after `stop` → `WordError("worker stopped")`. `stop` without `start` is a
  no-op.
- No `IMessageFilter`: the retry loop covers `RPC_E_CALL_REJECTED` (the COM
  backend maps it to `WordBusy`). Leave a short comment saying a message
  filter is a possible later improvement.

## Tests (use `FakeWordBackend`; keep each test under ~2 s)

- result returned; exception type and message propagate;
- `backend_factory` and `fn` run on the thread named `word-com`;
- order preserved for several submits;
- busy retry: `busy_calls=2` succeeds; `busy_calls=1000` with
  `busy_retry_total=0.3` raises `WordBusy` (monkeypatch the delay sequence or
  `time.sleep` to keep it fast);
- timeout: fake `hang` event unset, `call(timeout=0.2)` raises
  `WordNotResponding`; `is_stuck` true after `call_timeout`; further calls
  fail fast; after `hang.set()` the worker recovers and serves a new call;
- re-entrant call from inside `fn`;
- `stop` fails pending futures, calls `disconnect`, later calls raise;
  `stop` without `start`; context manager.

## Acceptance

README rule 7 commands; `uv run pytest tests/unit/test_worker.py -q` runs in
under 15 s.
