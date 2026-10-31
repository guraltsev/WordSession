# Job 14 — End-to-end CLI tests against real Word

Depends on: 09, 13
Plan reference: §6 Phase 3 exit criterion; §1.2 defects 2–6
Real Word: pre-approved (README rules 6 and 9).

## Goal

Prove, automatically and against real Word, that the new CLI does everything
the legacy tools did and fixes their known defects — before UI is built on
top of it. What cannot be automated goes to the final human test list.

## Files

- `scripts/make_test_docs.py`
- `tests/e2e/__init__.py`, `tests/e2e/conftest.py`, `tests/e2e/test_cli_word.py`,
  `tests/e2e/test_cli_shared_word.py`

## Do

1. `scripts/make_test_docs.py [DIR]` (default `%TEMP%\word-session-docs`):
   with a separate invisible Word (`DispatchEx`), create `alpha.docx`,
   `beta.docx`, `gamma.docx` (~10 pages of numbered paragraphs each) and
   `with space é.docx`; quit that Word; print the folder. The final human
   checklist (job 23) uses it; the tests reuse its function.
2. `tests/e2e/conftest.py`: an isolated Word backend that the CLI uses —
   call `main([...], service_factory=...)` with a factory that builds
   `SessionService` over a `ComWorker` whose backend factory returns
   `ComWordBackend(isolated=True)` sharing **one** isolated Word process
   for the whole test (keep the `Dispatch` object alive in the fixture and
   inject it; add a small `ComWordBackend.from_application(app)` classmethod
   in `word/com.py` if needed — it is the only allowed change outside
   `tests/` and `scripts/`). Store under `WORD_SESSION_HOME`.
3. `test_cli_word.py` (`@pytest.mark.word`), each scenario from the old
   tools and the plan's defect list:
   - `save` with three docs open and `beta` active → after save `beta` is
     still the active document (defect 2); `show latest --json` lists the
     three with positions;
   - close all, `restore` → three open, cursor offsets restored, `beta`
     active;
   - rename `gamma.docx` on disk, close all, `restore` → exit 4, `gamma`
     `missing`, the others open (defect 4);
   - open `alpha` in a *second* isolated Word, `restore` in the first →
     `alpha` `locked`, no dialog (the call returns within the timeout),
     others open (defect 5);
   - unsaved `Documents.Add()` + `save` → warning on stderr, document
     recorded as `unsaved`, skipped on restore (defect 6);
   - `with space é.docx` round-trips;
   - `restore --dry-run` makes no Word calls (document count unchanged);
   - `current --json` matches Word's open documents.
4. `test_cli_shared_word.py` (`@pytest.mark.shared_word`, README rule 9):
   against the human's Word via the default (non-isolated) backend:
   `current` lists the human's documents (read-only assertion: exit 0,
   valid JSON); open two temp docs via `restore` of a session that
   contains only them, check `already_open` on a second restore, then
   close them in teardown and re-activate the previously active document.
5. Items for the final human list (put them in the report's "For final
   human testing"): restore while Word shows a modal dialog (File →
   Options open) → `current` exits 6 within the timeout; `restore --no-start`
   with Word closed → exit 3 and Word does not start; `import-legacy`
   against the real `~/.word-session*` folders with a temp
   `WORD_SESSION_HOME`.

## Acceptance

```text
uv run pytest
WORD_SESSION_TEST_WORD=1 uv run pytest -m word tests/e2e
WORD_SESSION_TEST_SHARED_WORD=1 uv run pytest -m shared_word tests/e2e   # pass or skip with the ROT reason
```

No leftover `WINWORD.EXE` processes started by the tests.
