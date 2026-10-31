# Job 09 report
Status: done

## Changed files
- `src/word_session/word/com.py` (new)
- `tests/contract/conftest.py` (COM branch filled in; wrapper `_IsolatedContractBackend`)
- `tests/integration/__init__.py`, `tests/integration/conftest.py`,
  `tests/integration/test_com_backend.py`, `tests/integration/test_shared_word.py` (new)

## What was done
- `ComWordBackend(isolated=False)` implementing `WordBackend` with late binding only
  (`win32com.client.dynamic.Dispatch`), pywin32 imported lazily, attach via
  `GetActiveObject` + `QueryInterface(IID_IDispatch)`, start only when allowed,
  idempotent `connect` with a `Version` probe, `_translate_com_error` (busy codes ->
  `WordBusy`, otherwise `WordError` with Word's description; checks hresult and the
  excepinfo scode; DEBUG log), side-effect-free `list_documents` (plus protected view
  windows), `open_document` (already open / unsaved / missing / locked probe /
  alerts suppressed and restored), `restore_position`, `activate`, `disconnect`.
- Isolated mode uses `DispatchEx` (wrapped in a dynamic dispatch), invisible, quits
  with `Quit(wdDoNotSaveChanges)` on `disconnect`.
- Integration tests (11 in `test_com_backend.py`), 2 shared-Word tests, and the contract
  suite now runs against real Word (13 more tests).

## Acceptance results
```text
uv run ruff format --check .  -> clean (ruff format src tests: unchanged)
uv run ruff check .           -> All checks passed!
uv run pyright                -> 0 errors, 0 warnings, 0 informations
uv run pytest                 -> 1 failed, 274 passed, 30 skipped
   (the failure is tests/api/test_security.py::test_static_files_need_no_login,
    from another job; word/shared tests are skipped here)
WORD_SESSION_TEST_WORD=1 uv run pytest -m word            -> 28 passed
WORD_SESSION_TEST_SHARED_WORD=1 uv run pytest -m shared_word -> 2 passed
git grep -n -E "gencache|EnsureDispatch|client\.constants" src/ -> no output
```
WINWORD.EXE before: PID 60884 only (1 process). After every run: PID 60884 only (1).
One run showed a transient extra PID 68756 immediately after a run; it was gone
minutes later (started time not attributable; no test process remains).
The human's Word (60884) was never quit; shared tests only opened/closed temp docs.

## Deviations from the job text (and why)
1. `list_documents` iterates `Documents.Item` from last to first. Word returns the
   newest-opened document at index 1 (verified with 2 and 3 documents, order not
   changed by `Activate`), so the job's index order would flip the document order on
   every capture/restore round trip and fail the contract test (`[A, B]`).
2. `restore_position` re-activates the previously active document after selecting
   (the contract test requires restore not to change which document is active; the
   job says to `Activate()` the target, which is still done for the selection).
3. Offsets are clamped to `Content.End - 1`: Word raises "Value out of range" for
   `Range(Content.End, Content.End).Select()`.
4. `Documents.Open` is called with positional arguments
   `(path, False, read_only, False)`; late binding does not take keywords reliably.
   `Visible` is left at Word's default (True).
5. Isolated `connect(start_if_needed=False)` raises `WordUnavailable` when no private
   process is alive (required by the contract and the job's last test), rather than
   "always creating" a process.
6. Contract wrapper maps the contract's virtual paths (`C:\docs\A.docx`) to real temp
   `.docx` files and keeps Word alive on `disconnect`; `tests/contract/conftest.py`
   re-exports the `docx_factory`/`com_initialised` fixtures from the integration conftest.
7. Real-Word runs use `-p no:faulthandler`: pytest's faulthandler prints noisy
   "Windows fatal exception 0x800706be/ba" traces for handled COM RPC errors at Word
   shutdown; they are harmless. (`-p no:faulthandler` is not in pyproject.)

## Out-of-scope findings
- `tests/api/test_security.py::test_static_files_need_no_login` fails in the full run
  (other job's area, parallel work in progress).
- `src/word_session/doctor.py:204` has an invalid escape sequence `\W` in a docstring
  (SyntaxWarning); use a raw string.
- Faulthandler noise described in deviation 7 may affect any future real-Word runs.

## For final human testing
1. With Word open and a few documents, run a capture through the CLI/app once the
   service exists (job 11+); expect the active document and cursor not to change while
   listing and documents to be listed in the order they were opened (the oldest first).
   Notably: confirm Word's Documents order in the visible instance matches deviation 1
   (the shared test only checks membership, not order).
2. If shared tests skip with the ROT reason, click away from Word once (or open a
   document) and rerun `WORD_SESSION_TEST_SHARED_WORD=1 uv run pytest -m shared_word`.

## Notes for the coordinator
- Job 10 (worker) should keep calling the backend from the thread that connected;
  the backend does not call `CoInitialize`.
- Real-Word suites take about 2 minutes (each test starts its own hidden Word).
