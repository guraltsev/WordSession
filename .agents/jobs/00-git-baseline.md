# Job 00 — Git baseline

Depends on: —
Plan reference: §6 Phase 0, step 1
Pre-approved by the human: this job creates the first commit and a tag.

## Goal

Put the repository, exactly as it is today, under version control so every
later change is reviewable and the legacy code stays recoverable.

## Context

The repo was `git init`-ed but has no commits; the branch is `master`; the
intended default branch is `main` (`DECISIONS.md` D7). `venv/` contains its
own `.gitignore` with `*`, so it is already excluded.

This is the **only** job in which the executor commits.

## Do

1. Run `git status --porcelain=v1 --untracked-files=all` and check the list.
   It must contain only the project files (root scripts, `new/`, `_docs/`,
   `.agents/`, `.gitignore`, `.gitattributes`, `AGENTS.md`,
   `requirements.txt`, `.cmd`/`.ps1` files). If it contains anything else
   (e.g. `venv/` contents, `__pycache__`, `*.docx`, session JSON files with
   personal paths), stop and report.
   (If the baseline commit already exists — see step 3 — this check
   applies to `git status` instead and it must be clean.)
2. Rename the branch: `git branch -m main` (if that fails on an unborn
   branch, use `git symbolic-ref HEAD refs/heads/main`).
3. **If `git log` already shows a first commit whose subject starts with
   `Baseline:`** (the human had it created on 2026-10-31, before the run),
   skip this step and tag that commit in step 4. Otherwise `git add -A` and
   commit with message:

   ```text
   Baseline: legacy Word session scripts as found

   Snapshot before the migration described in _docs/migration_plan.md.
   ```

   followed by the session's attribution lines if any are required.
4. `git tag -a legacy-baseline -m "Legacy scripts before migration" <baseline commit>`.
5. Do not change any file content.

## Do not

- Do not push, add remotes, or change git config.
- Do not modify, move or delete files.

## Acceptance

```text
git log --oneline            # exactly one commit, subject "Baseline: ..."
git tag -l                   # legacy-baseline
git branch --show-current    # main
git status --porcelain       # empty
```

## Report

Standard report; include the commit hash and the output of
`git show --stat HEAD | tail -n 30`.
