# Changes log

Coordinator log of job-text edits and judgement calls (run started 2026-10-31).

- Start: baseline commit 9841936 already exists (branch master); job 00 will tag and rename.
- Job 00 accepted (baseline commit pre-existed; renamed to main, tagged). Report/status committed as job 00 bookkeeping.
- Job 02: executor's ruff format rewrote job texts 04-19 (md code blocks); coordinator restored them with git checkout, executor added [tool.ruff.format] exclude *.md (accepted).
- Human's WINWORD.EXE PID 60884 running at start of job 09 (baseline; never kill). Jobs 09/10 run in parallel (disjoint files).
- Job 06: coordinator added '-text' rule for tests/fixtures/legacy/* to .gitattributes (executor's suggestion; bytes must stay exact).
