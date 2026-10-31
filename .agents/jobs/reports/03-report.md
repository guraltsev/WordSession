# Job 03 report
Status: done
## Changed files
- `.github/workflows/ci.yml` (new)
## What was done
Workflow `ci` (push to main, pull_request) with job `checks` (windows-latest: checkout v4, setup-uv v5 with cache, uv python install, uv sync --frozen, ruff format --check, ruff check, pyright, pytest with coverage; trailing comment `# packaging: added in job 20`) and job `checks-linux` (ubuntu-latest: checkout, setup-uv, python install, sync --frozen, `pytest -m "not word and not ui"`).
## Acceptance results
- YAML parses via `uv run --with pyyaml`: jobs `['checks', 'checks-linux']`.
- ruff format --check: 6 files already formatted; ruff check: All checks passed; pyright: 0 errors; pytest with cov: 4 passed (TOTAL 76%); marker-filtered pytest: 4 passed.
## Deviations from the job text (and why)
- Added `uv python install` to the Linux job too (harmless; ensures `.python-version` 3.13). The job text lists only sync and pytest.
- Format/lint/pyright results were taken with job 04's concurrent changes possibly present in the tree.
## Out-of-scope findings
none
## For final human testing
none (workflow has not run remotely; no GitHub remote yet; coordinator to note in STATUS.md).
## Notes for the coordinator
Note in STATUS.md that the workflow has not run remotely. Nothing committed.
