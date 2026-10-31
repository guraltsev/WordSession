# Jobs

This folder breaks `docs/migration_plan.md` (before job 01: `_docs/migration_plan.md`)
into small, ordered jobs that a coding agent can execute one at a time.

- `COORDINATOR.md` — instructions for the agent (or human) that dispatches
  jobs, verifies them and commits.
- `DECISIONS.md` — design decisions the jobs assume. Confirm before starting.
- `STATUS.md` — one row per job; only the coordinator edits it.
- `NN-*.md` — the jobs. Run them in numeric order unless `STATUS.md` says
  otherwise.
- `reports/NN-report.md` — written by the agent that executed job `NN`.

## Rules for every job (read before starting any job)

1. **Read first**: `AGENTS.md`, `docs/python_rules.md`,
   `docs/docstring_schema.md`, `docs/tests.md` (once it exists), the job file,
   and the plan sections the job cites. Read the existing code you will
   touch. Do not rely on memory of other jobs.
2. **Stay in scope.** Change only the files the job lists, plus tests and
   docs the job asks for. If something outside scope is broken, write it in
   the report under "Out-of-scope findings"; do not fix it.
3. **Interfaces are fixed.** Names, signatures and behaviours written in a job
   are a contract later jobs rely on. If one is impossible or clearly wrong,
   stop and report instead of improvising.
4. **Import boundaries** (plan §3.1):
   - only `src/word_session/word/com.py` and `src/word_session/word/worker.py`
     import `pywin32` modules (`win32com`, `pythoncom`, `pywintypes`), and
     only inside functions or guarded by `try/except ImportError`;
   - only `src/word_session/web/` imports `fastapi`/`uvicorn`/`starlette`;
   - only `src/word_session/tray.py` imports `pystray`/`PIL`;
   - only `src/word_session/autostart.py`, `instance.py` and `doctor.py`
     import `winreg`/`win32event`, guarded the same way.
   Everything else must import on Linux/macOS too.
5. **Tests are part of the job.** New behaviour gets tests in `tests/`. No
   test may touch the user's real home, `%APPDATA%`, `%LOCALAPPDATA%` or a
   running Word: set `WORD_SESSION_HOME` to a `tmp_path` (fixture
   `isolated_home` in `tests/conftest.py`, created in job 02) and use
   `FakeWordBackend`. Tests that drive real Word are marked
   `@pytest.mark.word` and are skipped unless `WORD_SESSION_TEST_WORD=1`.
6. **Never** `git commit` (except job 00), `git push`, add remotes, or ask
   the user questions — the run is autonomous (DECISIONS D8); record
   ambiguities and your choice under "Deviations" in the report.
   `@pytest.mark.word` tests may be run whenever the job lists them in its
   acceptance (`WORD_SESSION_TEST_WORD=1`); they use isolated Word processes
   (`DispatchEx`) and must leave none behind.
7. **Definition of done** for every job, in addition to its own acceptance
   list:

   ```text
   uv run ruff format --check .
   uv run ruff check .
   uv run pyright
   uv run pytest
   ```

   all pass (from job 02 on).
8. **Manual checks.** Where a job says "manually", do it yourself with
   scripts, CLI calls or HTTP requests as far as possible. Anything that
   needs human eyes or hands (tray icon appearance, how the browser UI
   looks, notifications, Start menu, sign-in behaviour) goes in the
   report's "For final human testing" section as a concrete step with the
   expected result. Do not skip it silently.
9. **The human's Word instance** (tests marked `@pytest.mark.shared_word`,
   enabled with `WORD_SESSION_TEST_SHARED_WORD=1`, which the coordinator
   sets): the human has left a Word instance running for testing. Tests may
   attach to it (`GetActiveObject`), open and close **only documents they
   created in a temp folder**, and must restore the previously active
   document. They must never call `Quit`, close other documents, change
   options, or save anything outside the temp folder. If the instance is
   not reachable (`MK_E_UNAVAILABLE`: Word registers in the Running Object
   Table only after its window has lost focus once or a document is open),
   the tests skip with that explanation, and the step is added to "For
   final human testing".
10. **Report.** Write `.agents/jobs/reports/NN-report.md`:

   ```markdown
   # Job NN report
   Status: done | blocked | partial
   ## Changed files
   ## What was done
   ## Acceptance results   (paste the command outputs' last lines)
   ## Deviations from the job text (and why)
   ## Out-of-scope findings
   ## For final human testing   (numbered steps with expected results; "none" if none)
   ## Notes for the coordinator
   ```
