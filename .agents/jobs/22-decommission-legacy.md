# Job 22 — Decommission legacy

Depends on: 21
Plan reference: §6 Phase 7, §7
Outside the autonomous run: dispatch only when the human asks, after they
have finished testing (job 23 handoff) and used 1.0 for a while.

## Goal

Remove the legacy scripts from the working tree now that the new tool has
replaced them, while keeping old session files readable forever.

## Files

- delete `legacy/` (whole folder)
- `docs/migration_plan.md` (mark Phase 7 done, one line)
- `docs/development_guide.md` (remove references to `legacy/`)
- `.agents/jobs/README.md` (remove the instruction to read legacy code, if
  any job text still points there — leave job files themselves unchanged)

## Do

1. The human's request says whether the `.cmd` shims in the bundle (job
   20) are still used. If not, also remove
   `packaging/shims/` and the copy step in `build.ps1`, and note the
   removal in `CHANGELOG.md` under "Unreleased → Removed".
2. `git rm -r legacy/`.
3. Keep `src/word_session/legacy.py`, its tests and fixtures — the readers
   stay permanently (plan §7).
4. Grep for leftover references:
   `git grep -n -i -E "legacy/|word-session\.ps1|word_session_lib" -- . ':!CHANGELOG.md' ':!.agents/jobs/*.md'`
   and fix any in docs or code.

## Acceptance

- The grep above prints nothing.
- README rule 7 commands pass; packaging build + smoke test (job 20) pass.
- The tag `legacy-baseline` still exists.
