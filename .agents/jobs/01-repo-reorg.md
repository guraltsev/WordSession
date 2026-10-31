# Job 01 — Repository reorganisation

Depends on: 00
Plan reference: §1.1, §6 Phase 0 steps 2–5

## Goal

Remove duplication and dead weight, put the legacy scripts in one clearly
labelled place, and make the documentation paths that `AGENTS.md` cites
real.

## Context

- Root `word_session_lib.py`, `word-session.py`, `word-session-examples.py`
  are byte-identical to the copies in `new/`, and `word-session.py` in both
  places does not compile.
- `new/distrib/` holds the only working Python version (fixed CLI +
  PyInstaller spec).
- `requirements.txt` files are UTF-16 LE with BOM.
- `venv/` points at a Python install that no longer exists.
- `AGENTS.md` cites `docs/…` but the folder is `_docs/`; `docs/tests.md`
  does not exist; `_docs/development_guide.md` is empty.

## Do

Use `git mv` for every move so history follows the files.

1. Create `legacy/python/` and move into it from `new/distrib/`:
   `word-session.py`, `word_session_lib.py`, `word-session.spec`,
   `requirements.txt`.
2. Move `word-session-examples.py` (root copy) to
   `legacy/python/word-session-examples.py`.
3. Move `word-session-gui.py` to `legacy/wx-prototype/word-session-gui.py`.
4. Create `legacy/powershell/` and move `word-session.ps1` and the three
   `word-session-*.cmd` files into it.
5. `git rm` the root `word-session.py`, `word_session_lib.py`,
   `requirements.txt` and the whole `new/` folder (after steps 1–2, what is
   left there are duplicates).
6. Re-encode `legacy/python/requirements.txt` as UTF-8 without BOM, LF line
   endings. Content stays `pywin32==308`.
7. Write `legacy/README.md` (short): what each subfolder is, that
   `legacy/python/word-session.py` is the last working Python version, that
   these are kept read-only for reference until job 22, and that the full
   original tree is at tag `legacy-baseline`.
8. Delete the `venv/` folder from disk (it is untracked and broken).
9. `.gitignore`: in the "Project ignores" section add, one per line with a
   short comment line above the group: `venv/`, `build/`, `dist/`,
   `.coverage`, `htmlcov/`, `playwright-report/`, `test-results/`.
   Also fix the existing line `/.pytest-tmp/` only if it is malformed; do not
   reorder other sections.
10. `git mv _docs docs`.
11. Create `docs/tests.md` with the testing policy from plan §4: test levels
    table, the `word` marker and `WORD_SESSION_TEST_WORD=1`, the
    `WORD_SESSION_HOME` isolation rule, "no test touches the real home or a
    running Word", coverage targets, and the commands from README rule 7.
    Write it as policy for contributors (imperative, concise).
12. Fill `docs/development_guide.md`: prerequisites (Windows, Word, `uv`),
    `uv sync`, running checks and tests, running Word integration tests,
    where logs and sessions live (plan §3.4), project layout (plan §3.2,
    copied and kept short). Mark sections that refer to code not yet written
    with "(available after job NN)".
13. In `docs/migration_plan.md`, update only the §1.1 inventory note so it
    says the reorganisation is done (one line under the table:
    "Reorganised in job 01: see `legacy/`."). Do not rewrite the plan.
14. In `.agents/jobs/README.md`, replace
    "`docs/migration_plan.md` (before job 01: `_docs/migration_plan.md`)" with
    "`docs/migration_plan.md`".

## Do not

- Do not edit the legacy scripts' content (other than the requirements
  re-encoding).
- Do not create `pyproject.toml` or `src/` (job 02).

## Acceptance

```text
git status --short                        # only moves/deletes/new docs listed above
test ! -e new && test ! -e venv && test ! -e _docs
ls legacy/python legacy/powershell legacy/wx-prototype
file legacy/python/requirements.txt       # ASCII/UTF-8, not UTF-16
grep -n "docs/" AGENTS.md                 # every cited file exists:
ls docs/tests.md docs/docstring_schema.md docs/python_rules.md
```

(Use Git Bash for these commands.)

## Report

Standard report.
