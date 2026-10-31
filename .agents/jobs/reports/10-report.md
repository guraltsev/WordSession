# Job 10 report
Status: done

## Changed files
- src/word_session/word/worker.py (new)
- tests/unit/test_worker.py (new)

## What was done
Implemented `ComWorker` per the contract: one daemon thread `word-com`, optional
`pythoncom.CoInitialize/CoUninitialize`, backend created on that thread, FIFO
execution, busy retry (delays 0.1, 0.25, 0.5, 1, 2, 2, ... bounded by
`busy_retry_total`, DEBUG log per retry), caller-side timeout raising
`WordNotResponding`, `is_stuck` with fail-fast `call`/`submit`, re-entrancy,
`stop` (pending futures get `WordError("worker stopped")`, `disconnect()` on
worker thread), context manager. 13 unit tests with `FakeWordBackend`.

## Acceptance results
- `uv run ruff format --check .`: 26 files already formatted
- `uv run ruff check .`: All checks passed!
- `uv run pyright`: 0 errors, 0 warnings, 0 informations
- `uv run pytest tests/unit/test_worker.py -q`: 13 passed in ~0.9 s (3 runs, stable)
- `uv run pytest -q`: 112 passed, 17 skipped, 1 failed:
  `tests/unit/test_legacy.py::test_import_is_idempotent_and_leaves_sources_alone`
  (not my file; see out-of-scope).

## Deviations from the job text (and why)
- `submit`/`call` before `start` raise `WordError("worker not started")` (job was silent).
- If `backend_factory` raises on the worker thread, the error is stored and every
  job's future fails with it (job was silent).
- Busy-retry delays live in module constant `_BUSY_DELAYS` so tests can shorten them.
- A `call` that times out leaves its job queued/running; if the worker is stopped
  before it starts, that job fails with "worker stopped".

## Out-of-scope findings
- `tests/unit/test_legacy.py::test_import_is_idempotent_and_leaves_sources_alone`
  fails in the whole-repo run; legacy code is from another job and I did not investigate.

## For final human testing
none

## Notes for the coordinator
Job 09 files were present during the whole-repo run; all checks other than the
test_legacy failure passed repo-wide. Nothing committed.
