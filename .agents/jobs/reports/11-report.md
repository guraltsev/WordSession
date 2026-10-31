# Job 11 report
Status: done
## Changed files
- src/word_session/events.py (new)
- src/word_session/service.py (new)
- tests/unit/test_events.py, tests/unit/test_service.py (new)
- tests/conftest.py (added fixtures fake_backend, worker, fixed_clock, service; existing ones kept)
## What was done
EventBus and SessionService with every behaviour in the job text (capture, restore with per-document report and events, list/get/revision/update/delete/prune/diff, legacy import, autosave_tick, close, open_service with fake demo mode).
## Acceptance results
- ruff format --check .: 35 files already formatted
- ruff check .: All checks passed!
- pyright: 0 errors, 0 warnings, 0 informations
- pytest: 149 passed, 30 skipped (word / shared_word markers)
Whole-repo checks passed, including the other executor's in-progress files at the time of the run.
## Deviations from the job text (and why)
- restore connects to Word only when at least one document actually needs Word; if every document is skipped/missing/dry-run no connect happens (avoids starting Word for nothing).
- restore_started is published after the connect succeeds (so a WordUnavailable publishes nothing, matching "nothing is reported as attempted"). total counts all selected documents, including skipped/missing ones.
- restore passes only the document to open_document (default read_only=False).
- Messages for pre-settled results: unsaved -> "never saved", missing -> "file not found".
- autosave_tick builds the candidate session once (via internal _snapshot) to compare fingerprints and then saves it, instead of calling capture() and comparing afterwards, so a skipped tick writes nothing. Emitted events/ids are the same as capture(kind="auto").
- An empty capture returns a Session with id "" (never stored); no id is reserved.
- open_service imports ComWordBackend lazily inside the non-fake branch; fake mode uses three demo docs thesis/notes/todo under C:\Demo\.
## Out-of-scope findings
none
## For final human testing
none (service is exercised only through FakeWordBackend; real-Word behaviour is covered by job 09/10 suites).
## Notes for the coordinator
- The restore flag is a plain bool guarded by a lock for acquisition; restore_in_progress reads it without the lock.
- tests/unit/test_service.py accesses service._restoring directly in two autosave tests.
- I did not touch com.py, tests/contract, tests/integration or .agents/jobs/*.md.
