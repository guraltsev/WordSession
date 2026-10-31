# Job 09 — COM backend

Depends on: 08
Plan reference: §3.5 rules 1–3, 6–10; §1.2 defects 2–8, 13
Real Word: pre-approved. Run `WORD_SESSION_TEST_WORD=1 uv run pytest -m word`
(isolated hidden Word processes) and the `shared_word` tests under README
rule 9.

## Goal

Implement `WordBackend` on top of real Word through pywin32, fixing the
legacy defects: no gen_py cache, attach-vs-start kept distinct, capture
without changing the active document, per-document errors, dialogs
suppressed, offset-based positioning.

## Files

- `src/word_session/word/com.py`
- `tests/contract/conftest.py` (fill the `TODO(job 09)` branch)
- `tests/integration/__init__.py`, `tests/integration/conftest.py`,
  `tests/integration/test_com_backend.py`

Read `legacy/python/word_session_lib.py` first to see what the old code did.

## Contract

```python
class ComWordBackend:               # implements WordBackend
    def __init__(self, *, isolated: bool = False) -> None: ...
```

`isolated=False` (normal use): attach to the user's Word.
`isolated=True` (tests only): `connect` always creates a **new, invisible**
Word process with `win32com.client.DispatchEx("Word.Application")`;
`disconnect` quits it with `Quit(SaveChanges=wdDoNotSaveChanges)`. Never
attaches to the user's Word. Say so in the docstring.

## Implementation rules

1. Imports of `win32com.client`, `pythoncom`, `pywintypes` happen inside
   methods (or a module-level `try/except ImportError` that makes
   construction raise `WordUnavailable("pywin32 is not installed")`), so the
   module imports on Linux.
2. **Late binding only.** Use `win32com.client.dynamic.Dispatch`. Never
   `gencache`/`EnsureDispatch`/`win32com.client.constants`; use
   `word.constants`.
3. **Attach**: `pythoncom.GetActiveObject(pywintypes.IID("Word.Application"))`,
   then `.QueryInterface(pythoncom.IID_IDispatch)`, then
   `win32com.client.dynamic.Dispatch(...)`. `com_error` with hresult
   `MK_E_UNAVAILABLE` means "not running".
4. **Start** (only when `start_if_needed=True`):
   `win32com.client.dynamic.Dispatch("Word.Application")`, then
   `Visible = True`. Failure to create (not installed) → `WordUnavailable`.
5. `connect` is idempotent: if already connected, probe with `app.Version`;
   if that fails (Word was closed), reconnect according to `start_if_needed`.
6. **Error translation**: wrap every COM access. `pywintypes.com_error`
   with hresult in (`RPC_E_CALL_REJECTED`, `RPC_E_SERVERCALL_RETRYLATER`) →
   `WordBusy`; otherwise `WordError(<Word's excepinfo description or str(exc)>)`.
   Keep this in one private function `_translate_com_error(exc) -> WordError`.
   Log every translated error at DEBUG with the hresult.
7. **`list_documents` without side effects** (fixes legacy `Activate()`):
   - `active_name = app.ActiveDocument.FullName` if `app.Documents.Count`
     (catch errors → `None`);
   - for `i in 1..Documents.Count`: `doc = app.Documents.Item(i)`,
     `win = doc.Windows.Item(1)`, `sel = win.Selection`;
     `start, end = sel.Start, sel.End`;
     `page = sel.Information(wdActiveEndPageNumber)`,
     `line = sel.Information(wdFirstCharacterLineNumber)` (values ≤ 0 → `None`);
     `read_only = bool(doc.ReadOnly)`, `had_unsaved_changes = not doc.Saved`,
     window state mapped from `win.WindowState`;
     `active = FullName == active_name`;
   - then each `app.ProtectedViewWindows.Item(j)` as a document with
     `read_only=True`, empty position, `active=False`;
   - never call `Activate`, `Select`, `GoTo`.
   - A failure on one document is logged and that document is still listed
     with whatever was read (at least `path`); it does not abort the list.
8. **`open_document`**:
   - already open (case-insensitive `FullName`) → `"already_open"`;
   - `location == "unsaved"` → `WordError("document was never saved")`;
   - `local`/`unc`: missing file → `DocumentMissing`; if not `read_only`,
     detect a lock by trying `open(path, "r+b")` and catching
     `PermissionError` → `DocumentLocked` (Word holds files with deny-write;
     CPython opens with share read/write, so this probe does not lock);
   - `url`: no existence check;
   - save `app.DisplayAlerts`, set `wdAlertsNone`, call
     `app.Documents.Open(FileName=path, ConfirmConversions=False,
     ReadOnly=read_only, AddToRecentFiles=False, Visible=True)`, restore
     `DisplayAlerts` in `finally`.
9. **`restore_position`**: find the open document; if `position.start` is
   not `None`: `length = doc.Content.End`, clamp `start`/`end` (default end
   = start) into `[0, length]`, `doc.Activate()`, `doc.Range(s, e).Select()`,
   then `doc.Windows.Item(1).ScrollIntoView(doc.Range(s, e))` (ignore
   failures of the scroll). Else if `page`: GoTo page absolute, then line
   relative `line - 1` (legacy behaviour) on that document's window
   selection. Else nothing.
10. **`activate`**: `doc.Activate()` for the matching open document; unknown
    path → `WordError`.
11. **`disconnect`**: drop the reference (`self._app = None`); in isolated
    mode quit first. Never raises (log instead).
12. Everything is synchronous and assumes the calling thread has COM
    initialised (job 10 guarantees that). Do not call `CoInitialize` here.

## Integration tests (`@pytest.mark.word`)

`tests/integration/conftest.py`:

- `pythoncom.CoInitialize()` per test thread (fixture, with
  `CoUninitialize` at teardown);
- fixture `word` → connected `ComWordBackend(isolated=True)`, disconnected
  at teardown even on failure;
- fixture `docx_factory(tmp_path)` → creates real `.docx` files using a
  separate isolated Word app: `Documents.Add()`, insert ~200 numbered
  paragraphs (several pages), `SaveAs2(str(path))`, `Close()`.

Tests (each self-contained, only temp files):

- empty instance lists nothing; `info()` values;
- open two docs → listed in order, exactly one active; listing does not
  change `ActiveDocument`;
- set a selection via `Range(1234, 1240).Select()`, capture, close all,
  open again, `restore_position` → `Selection.Start == 1234`;
- clamping: start beyond length does not raise, ends at document end;
- page/line fallback when `start` is `None`;
- missing file → `DocumentMissing`;
- locked file: open it in a *second* isolated Word, then `open_document`
  in the first → `DocumentLocked`; `read_only=True` succeeds;
- already open with different case → `"already_open"`;
- unsaved document (`Documents.Add()` without save) → `location == "unsaved"`;
- `connect(start_if_needed=False)` on an isolated backend whose process was
  quit raises `WordUnavailable` or reconnects only when allowed.

Fill `tests/contract/conftest.py`'s `"com"` branch with the same isolated
fixture + `docx_factory` so the contract suite runs against real Word.

## Shared-Word tests (`@pytest.mark.shared_word`, README rule 9)

`tests/integration/test_shared_word.py` exercises the **attach** path that
isolated tests cannot reach, against the Word instance the human left
running:

- fixture `shared_word`: `ComWordBackend()` (not isolated);
  `connect(start_if_needed=False)`; on `WordUnavailable` →
  `pytest.skip("user's Word not reachable over COM (not in the ROT yet)")`.
  Records `ActiveDocument.FullName` (if any) and the list of open document
  paths before the test.
- teardown (always): close every document whose path is under the test's
  `tmp_path` with `wdDoNotSaveChanges`; re-activate the previously active
  document; assert the set of other open documents is unchanged; call
  `disconnect()` (never `Quit`).
- tests: `is_running()` true; `info()`; open two temp docs (created by an
  isolated Word via `docx_factory`), `list_documents()` contains them and
  the previously open documents, exactly one active, and listing did not
  change the active document; `restore_position` on a temp doc;
  `already_open` on the second open.

## Acceptance

```text
uv run pytest                                   # word tests skipped
WORD_SESSION_TEST_WORD=1 uv run pytest -m word  # all pass
WORD_SESSION_TEST_SHARED_WORD=1 uv run pytest -m shared_word   # pass, or skip with the ROT reason
git grep -n -E "gencache|EnsureDispatch|client\.constants" src/   # no output
```

After the Word tests, confirm no stray `WINWORD.EXE` processes started by
the tests remain (`tasklist /FI "IMAGENAME eq WINWORD.EXE"` — compare with a
count taken before running; report both counts).
