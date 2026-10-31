# Coordinator job

You coordinate the migration described in `docs/migration_plan.md`
(`_docs/migration_plan.md` until job 01 has run). You dispatch the numbered
jobs in this folder to executor agents, verify their work independently,
commit accepted work, and keep `STATUS.md` truthful.

**You run autonomously from job 00 to job 23 without asking the human
anything.** The human has pre-approved every step in this file (2026-10-31)
and will test and debug only at the very end, from the handoff that job 23
produces. Do not stop for confirmations, decisions or gates; when something
is unclear, decide using the rules below, record the decision, and keep
going.

You do not write product code yourself, except as allowed in "Fixing a stuck
job".

## Inputs

- `.agents/jobs/README.md` — rules every executor follows. You enforce them.
- `.agents/jobs/DECISIONS.md` — design decisions (all settled; do not ask).
- `.agents/jobs/STATUS.md` — the job table. You are its only editor.
- `.agents/jobs/CHANGES.md` — your log of every change you make to job texts
  and every judgement call (create it on first use).
- `.agents/jobs/NN-*.md` — job specs.
- `.agents/jobs/reports/NN-report.md` — executor reports.

## Pre-approved by the human

- Creating the baseline commit, tag `legacy-baseline`, and renaming the
  branch to `main` (job 00).
- Committing every accepted job locally. (Never push; never add remotes.)
- Running `@pytest.mark.word` tests. Isolated tests start their own hidden
  Word processes and must clean them up.
- Using the human's running Word instance for tests marked `shared_word`
  (job 09/14), under README rule 9. Never close that Word, never close or
  modify documents the tests did not create.
- Silent install/uninstall of the built installer into a temp directory
  (job 21).

Not approved: pushing, publishing, tagging releases, deleting the
`legacy-baseline` tag, rewriting history after job 00, modifying the human's
real sessions/config (`%APPDATA%\word-session`, `~/.word-session*`) — tests
always use `WORD_SESSION_HOME`.

## Loop

Repeat until every job up to 23 is `done` or `blocked`.

1. **Pick the next job**: the lowest-numbered job in state `todo` whose
   `Depends on` jobs are all `done`. If a dependency is `blocked`, mark the
   dependent `blocked` too (note "blocked by NN") and move on. Independent
   jobs may run in parallel only if they touch disjoint files; when in
   doubt run them sequentially.
2. **Pre-flight**: the working tree must be clean (`git status --porcelain`
   empty) except for files under `.agents/jobs/`. If not, find out why and
   restore a clean state (`git stash push -u -m "stray before job NN"`,
   noted in `CHANGES.md`) before continuing.
3. **Dispatch.** Set state `in-progress`, increment `Attempts`. Give the
   executor this prompt (fill in the blanks):

   > You are executing job NN of the Word Session migration in
   > `<repo path>`. Read `.agents/jobs/README.md` and follow its rules
   > exactly, then read and carry out `.agents/jobs/NN-<name>.md`. Do not
   > commit. Do not ask the user questions; if something is ambiguous,
   > choose the option most consistent with the job text and the plan and
   > record it under "Deviations". When finished, write
   > `.agents/jobs/reports/NN-report.md` in the format the README specifies
   > and stop.
   > <On a retry, append: "A previous attempt was rejected. Feedback:
   > `.agents/jobs/reports/NN-review-K.md`. Address every point.">

4. **Verify** when the executor stops. Set state `review`. Do all of:
   - Read the report. `blocked`/`partial` → step 6.
   - `git status` and `git diff --stat`: every changed file is within the
     job's scope (its "Files" list, `tests/`, the docs it names, its
     report). Unexpected files → reject.
   - Run the README's definition-of-done commands yourself, plus every
     command in the job's **Acceptance** section — including
     `WORD_SESSION_TEST_WORD=1` runs where the job lists them. Do not trust
     pasted output.
   - Read the diff against the job text: required names and signatures
     exist and match; listed behaviours have tests; import boundaries hold
     (`git grep -n -E "import (win32com|pythoncom|pywintypes|fastapi|uvicorn|pystray|winreg|win32event)" src/`
     only in the modules README rule 4 allows); docstrings follow
     `docs/docstring_schema.md`; code follows `docs/python_rules.md`.
   - Tests are meaningful: an assertion per listed behaviour, no tests that
     only assert `True`, no skips except the `word`/`shared_word`/`ui`
     markers and platform skips, nothing touching the real home.
   - After any Word tests: no leftover `WINWORD.EXE` processes beyond the
     count before the run (`tasklist /FI "IMAGENAME eq WINWORD.EXE"`). Kill
     only processes that the test run started (compare PIDs before/after);
     never the human's.
5. **Accept**: stage exactly the job's files and its report, commit:

   ```text
   job NN: <job title>

   <two-line summary from the report>
   ```

   plus the attribution lines your session requires. Set state `done`,
   record the short hash, append the report's "For final human testing"
   items to `.agents/jobs/reports/human-test-items.md` (job number +
   item), and continue.
6. **Reject**: write `.agents/jobs/reports/NN-review-K.md` (K = attempt)
   with a numbered list of concrete defects: file, what is wrong, what the
   job text requires. Keep the tree; the next attempt fixes on top of it
   (stash only if unrecoverable, noted in `STATUS.md`). Attempts < 3 → state
   `todo`, re-dispatch with the retry prompt. Attempts = 3 → "Fixing a stuck
   job".

## Fixing a stuck job

Use these, in order, and log each in `CHANGES.md`:

1. **Contract problem in the job text** (the executor reports a signature,
   behaviour or dependency that cannot work, or you see it yourself): edit
   the job text to the smallest change that works, consistent with the plan
   and with jobs already `done`. Check later jobs that reference the changed
   names and update them too. Reset `Attempts` to 0 and re-dispatch.
2. **Executor keeps failing on a narrow point** after 3 attempts with a
   correct job text: you may make the fix yourself if it is ≤ 30 changed
   lines, then run the full verification and accept with the commit body
   noting "coordinator fix".
3. **Environment problem** (e.g. a dependency does not install, a tool is
   missing, Word cannot be automated at all): try the documented
   alternative (e.g. D2 fallback, skip the optional installer step), record
   it in `DECISIONS.md`/`CHANGES.md`, and continue. If no alternative
   exists, mark the job `blocked` with the reason and continue with jobs
   that do not depend on it.

Never weaken a test or acceptance criterion to make a job pass, except a
real-Word test that is impossible in this environment — then mark that test
for the human in `human-test-items.md` instead of deleting it.

## Design decisions

`DECISIONS.md` is settled. If a job reveals that a decision cannot work,
choose the documented alternative, update the row with the date and reason,
and log it in `CHANGES.md`. Do not ask the human.

## Talking to the human

Do not. The only message to the human is the final handoff (job 23). If the
session is interrupted and resumed, read `STATUS.md` and `CHANGES.md` and
continue the loop silently.

## Finishing

After job 23 is `done` (or every remaining job is `blocked`), send the
handoff message that job 23 specifies and stop. Job 22 (removing the legacy
scripts) is **not** part of the run: it stays `todo` until the human has
finished testing and asks for it.
