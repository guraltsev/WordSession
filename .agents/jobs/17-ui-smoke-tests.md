# Job 17 — UI smoke tests (Playwright)

Depends on: 16
Plan reference: §4 (UI row)

## Goal

Lock in the main UI flows with a few browser tests that run against the
demo backend, so later changes to the UI or API cannot silently break them.

## Files

- `pyproject.toml` (dev deps `pytest-playwright>=0.5`)
- `tests/ui/__init__.py`, `tests/ui/conftest.py`, `tests/ui/test_flows.py`
- `docs/tests.md` (add how to run UI tests)

## Do

1. All tests in `tests/ui/` are marked `ui` (module-level `pytestmark`).
   They are skipped unless `WORD_SESSION_TEST_UI=1` (job 02 hook).
2. `conftest.py`: session-scoped fixture that builds a service with
   `open_service(fake=True)` under a temp `WORD_SESSION_HOME`, starts
   `start_server(port=0)`, and yields `(handle, service)`; a `logged_in_page`
   fixture that mints a login code and navigates the Playwright `page` to
   the login URL.
3. Flows (each test independent; reset the store between tests by deleting
   all sessions through the service):
   - save a session from `#/sessions`, it appears in the table;
   - open detail, rename inline, reload page, new name persists;
   - pin toggle;
   - restore with one document unchecked → progress panel → report shows
     the unchecked document absent and others `opened`/`already_open`;
   - two pages (two logins) open; save in page 1 → appears in page 2
     without reload within 3 s;
   - edit conflict: both pages on the same detail; rename in page 1, then
     rename in page 2 → page 2 shows the "changed in another tab" toast;
   - visiting the app with a fresh browser context (no cookie) → "Not
     signed in" message;
   - stopping the server → banner "Word Session is not running".
4. In `docs/tests.md` document: `uv run playwright install chromium`, then
   `WORD_SESSION_TEST_UI=1 uv run pytest -m ui`.

## Acceptance

```text
uv run playwright install chromium
WORD_SESSION_TEST_UI=1 uv run pytest -m ui      # all pass
uv run pytest                                   # ui tests skipped, rest green
```
