# Job 23 report
Status: done (installer-related verification not possible, see Deviations)

## Changed files
- `docs/acceptance_checklist.md` (new)
- `.agents/jobs/reports/23-report.md` (new)

## What was done
- Read STATUS, CHANGES, all reports, human-test-items.
- Re-ran the full verification (results below) and wrote the human checklist: setup, automated results with per-module coverage, 11+4+13+11+3+3+11 manual steps grouped A-G (all items of `human-test-items.md` included, de-duplicated, plus the required modal-dialog timeout, `--no-start`, legacy import into a temp home, tray menu/notifications, two tabs, start at login), known issues, deviations, bug reporting, after testing.

## Acceptance results
- `ruff format --check .`: 79 files already formatted
- `ruff check .`: All checks passed
- `pyright`: 0 errors, 0 warnings, 0 informations
- `pytest -p no:faulthandler --cov=word_session`: 358 passed, 48 skipped; total coverage 88% (`word/com.py` 14%)
- `WORD_SESSION_TEST_WORD=1 pytest -m word`: 36 passed, 370 deselected (3 min 46 s)
- `WORD_SESSION_TEST_SHARED_WORD=1 pytest -m shared_word`: 4 passed
- `WORD_SESSION_TEST_UI=1 pytest -m ui`: 8 passed
- `packaging/build.ps1 -NoSync`: built `dist\WordSession-0.1.0-win64.zip` (0.1.0 because venv metadata is stale)
- `packaging/smoke_test.ps1 -Dist dist/WordSession`: "smoke test passed" (`word-session 0.1.0`)
- WINWORD PIDs before and after the Word and shared-Word runs: identical (60884 plus the nine known leaks). No new leftovers.
- Uses `uv run --no-sync` throughout; no processes killed.

## Deviations from the job text (and why)
- Used `uv run --no-sync` and `build.ps1 -NoSync` (locked exe); `build.ps1 -Installer` not run (no Inno Setup).
- `smoke_test.ps1` has a mandatory `-Dist` parameter, so it was run with `-Dist dist/WordSession`.
- Coverage was measured in the normal run (real-Word tests not included), so `com.py` shows 14%.

## Out-of-scope findings
- Known issue: venv metadata says 0.1.0 while pyproject says 1.0.0; bundle built is 0.1.0-named. A clean `uv sync` after the strays end fixes it. Venv not deleted.
- Leaked hidden Word PIDs 70684, 15024, 62392, 61516, 73048, 71828, 73376, 74820, 75576 still present, plus human Word 60884. A `word-session.exe` PID 70648 was running after the smoke test (not started by me knowingly; probably an older stray); not killed.
- No failures to list. The SyntaxWarning in `doctor.py` noted in job 09 did not appear (only an httpx deprecation warning from Starlette).
- `docs/development_guide.md` lacks `-Installer`.

## For final human testing
See `docs/acceptance_checklist.md` sections A to G (everything there).

## Notes for the coordinator
- Working tree changes from me: the two files above only (STATUS.md was already modified before I started).
- Not committed.
