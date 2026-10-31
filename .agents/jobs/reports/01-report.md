# Job 01 report
Status: done

## Changed files
- Moved (`git mv`) into `legacy/python/`: `word-session.py`, `word_session_lib.py`, `word-session.spec`, `requirements.txt` (from `new/distrib/`), `word-session-examples.py` (root copy).
- Moved to `legacy/wx-prototype/word-session-gui.py`; `word-session.ps1` and the three `word-session-*.cmd` to `legacy/powershell/`.
- Removed: root `word-session.py`, `word_session_lib.py`, `requirements.txt`, and all of `new/`.
- `legacy/python/requirements.txt` re-encoded (UTF-8, LF, `pywin32==308`).
- New: `legacy/README.md`, `docs/tests.md`.
- `_docs/` renamed to `docs/`; filled `docs/development_guide.md`; one line added to `docs/migration_plan.md` under the §1.1 table.
- `.gitignore`: appended groups under "Project ignores".
- `.agents/jobs/README.md`: line 3 reference fixed.
- `venv/` deleted from disk (untracked).

## What was done
All 14 steps of the job.

## Acceptance results
- `new`, `venv`, `_docs` do not exist.
- `ls legacy/python legacy/powershell legacy/wx-prototype` shows the expected files.
- `file legacy/python/requirements.txt`: ASCII text.
- `docs/tests.md`, `docs/docstring_schema.md`, `docs/python_rules.md` all exist.
- git status shows only renames/deletes plus modified `.gitignore` and new docs (the new files are untracked or staged by git mv only).
- Ruff/pyright/pytest not applicable (no project until job 02).

## Deviations from the job text (and why)
- `.gitignore` additions are two comment-headed groups (environments/build; test/coverage output) rather than a single group; `.venv/` already existed, `/.pytest-tmp/` was well-formed and untouched.
- `docs/tests.md` also documents the `shared_word` marker (README rule 9).

## Out-of-scope findings
- `docs/migration_plan.md` still contains other `_docs`/`new/` references in historical text (inventory table, §3.2); left as instructed.

## For final human testing
none

## Notes for the coordinator
- Nothing committed. New files (`legacy/README.md`, `docs/tests.md`) and edits are not staged; the moves/deletes are staged.
- The CRLF/LF normalisation of the moved `.cmd`/`.ps1` is governed by `.gitattributes`; contents not edited.
