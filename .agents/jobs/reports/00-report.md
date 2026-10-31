# Job 00 report
Status: done
## Changed files
None (only git refs changed: branch renamed, tag created). This report file added.
## What was done
- Baseline commit 9841936 ("Baseline: legacy Word session scripts, migration plan and agent jobs") already existed; step 3 skipped.
- `git branch -m main` (master -> main).
- `git tag -a legacy-baseline -m "Legacy scripts before migration" 9841936`.
## Acceptance results
- git log --oneline: `9841936 Baseline: legacy Word session scripts, migration plan and agent jobs` (one commit)
- git tag -l: `legacy-baseline`
- git branch --show-current: `main`
- git status --porcelain: only coordinator edits ` M .agents/jobs/STATUS.md`, `?? .agents/jobs/CHANGES.md` (ignored as instructed; otherwise clean)
- git show --stat HEAD | tail: 53 files changed, 5365 insertions(+) (includes .agents/jobs/*, _docs/*, new/*, root scripts, .cmd/.ps1, .gitignore, .gitattributes, AGENTS.md, requirements.txt)
## Deviations from the job text (and why)
- Commit hash 9841936's subject differs from the job's template text; job step 3 explicitly allows a pre-existing "Baseline:" commit.
- Clean-tree check tolerated the coordinator's uncommitted edits under .agents/jobs/.
## Out-of-scope findings
- Docs live in `_docs/` (not `docs/`) at this point; AGENTS.md references `docs/`, to be handled by job 01.
## For final human testing
none
## Notes for the coordinator
The baseline commit does not include the coordinator's STATUS.md edit or CHANGES.md; commit them as you see fit.
