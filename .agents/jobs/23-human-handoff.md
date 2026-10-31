# Job 23 — Human handoff

Depends on: 21 (or every remaining job `blocked`)
Plan reference: §6 exit criteria of all phases

## Goal

Hand the human one document from which they can test and debug the whole
tool in a single sitting: what was built, what was verified automatically,
what they need to check by hand, and what is known to be incomplete.

## Files

- `docs/acceptance_checklist.md`
- `.agents/jobs/reports/23-report.md`

## Do

1. Read `STATUS.md`, `CHANGES.md`, every `reports/NN-report.md`, and
   `reports/human-test-items.md`.
2. Run the full verification once more and record the results:
   `uv run ruff format --check .`, `uv run ruff check .`, `uv run pyright`,
   `uv run pytest --cov=word_session`, `WORD_SESSION_TEST_WORD=1 uv run pytest -m word`,
   `WORD_SESSION_TEST_SHARED_WORD=1 uv run pytest -m shared_word`,
   `WORD_SESSION_TEST_UI=1 uv run pytest -m ui`, `packaging/build.ps1`,
   `packaging/smoke_test.ps1`. Do not fix failures here; list them.
3. Write `docs/acceptance_checklist.md` for the human:
   - **Setup**: where the built bundle/installer is, how to run from
     source (`uv sync`, `uv run word-session …`), how to use a throwaway
     `WORD_SESSION_HOME` for testing versus their real data,
     `scripts/make_test_docs.py` for sample documents, where logs are.
   - **Automated results**: table of the commands above with pass/fail and
     counts (tests passed/skipped/failed, coverage per module).
   - **Manual checks**, grouped (CLI with real Word, browser manager, tray,
     autosave, packaging/installer, legacy import): every item from
     `human-test-items.md`, de-duplicated, as numbered steps with exact
     commands and the expected result, plus a pass/fail/notes column. Always
     include: the modal-dialog timeout, `--no-start` with Word closed,
     importing their real legacy sessions into a temp home, tray menu and
     notifications, two browser tabs staying in sync, start at login.
   - **Known issues and deviations**: every `blocked` job and why, every
     coordinator fix and job-text change from `CHANGES.md`, every
     "Deviations" entry from reports that changes behaviour.
   - **How to report a bug**: run `word-session doctor --json`, attach the
     log tail, note the checklist step number.
   - **After testing**: tag `v1.0.0` when satisfied; ask for job 22 to
     remove `legacy/`.
4. Commit is done by the coordinator as usual.

## Handoff message (sent by the coordinator after accepting this job)

The coordinator's final and only message to the human, at most 15 lines:
what is done (jobs done/blocked, commit range), headline automated
results, the link `docs/acceptance_checklist.md`, the three most important
things to test first, and known blockers.

## Acceptance

`docs/acceptance_checklist.md` exists, every item in `human-test-items.md`
appears in it, and every `blocked` job and `CHANGES.md` entry is listed
under known issues.
