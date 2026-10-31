# Job 19 report
Status: done
## Changed files
- src/word_session/autosave.py (new)
- src/word_session/app.py (start/stop Autosaver, `trigger_autosave`)
- src/word_session/web/app.py (`on_settings_changed` in `create_app`, called after PUT /api/settings)
- src/word_session/web/server.py (`start_server(on_settings_changed=...)` pass-through)
- src/word_session/tray.py (Autosave toggle calls `app.trigger_autosave()`)
- tests/unit/test_autosave.py (new)
- tests/unit/test_app.py (FakeApp gained `trigger_autosave`)
## What was done
Autosaver per contract: daemon thread "autosave", interruptible Event wait, interval read fresh each loop, enabled check, backoff x2 up to x4 on `autosave_failed` (or unexpected exception), reset on success, `last_error`/`last_saved_id`. App starts it after the server and stops it first on teardown. Tray warning state already reacted to `autosave_failed`/`session_saved` events (job 18), so unchanged.
## Acceptance results
ruff format --check: 75 files already formatted; ruff check: All checks passed; pyright: 0 errors; pytest: 354 passed, 48 skipped.
## Deviations from the job text (and why)
- Touched `web/server.py` and `tray.py` and `tests/unit/test_app.py` (not listed): needed to route the callback from `start_server` into `create_app` and to call `trigger()` from the tray toggle.
- A tick that saves nothing (no change) counts as success for backoff; the tray warning clears only on an `auto` `session_saved`, so a warning may persist until the next actual save.
- The first tick happens after one interval (no immediate tick on start).
- `uv run` failed on a locked exe; used `uv run --no-sync`.
## Out-of-scope findings
none
## For final human testing
1. `word-session --demo app`, set interval 1 minute in Settings with a changing demo state: an `auto` session appears within about a minute.
2. Untick "Autosave" in the tray: no new `auto` sessions appear.
## Notes for the coordinator
Full-repo checks passed including other jobs' in-progress files.
