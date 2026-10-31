# Changes log

Coordinator log of job-text edits and judgement calls (run started 2026-10-31).

- Start: baseline commit 9841936 already exists (branch master); job 00 will tag and rename.
- Job 00 accepted (baseline commit pre-existed; renamed to main, tagged). Report/status committed as job 00 bookkeeping.
- Job 02: executor's ruff format rewrote job texts 04-19 (md code blocks); coordinator restored them with git checkout, executor added [tool.ruff.format] exclude *.md (accepted).
- Human's WINWORD.EXE PID 60884 running at start of job 09 (baseline; never kill). Jobs 09/10 run in parallel (disjoint files).
- Job 06: coordinator added '-text' rule for tests/fixtures/legacy/* to .gitattributes (executor's suggestion; bytes must stay exact).
- Job 15 report: EventSource cannot send X-Word-Session header; edited job 16 text to use fetch-streamed SSE parsing instead (header rule kept).
- Job 09: coordinator re-ran 30 word+shared_word tests (pass, only human PID 60884 remains). Out-of-scope: doctor.py:204 invalid \W escape in docstring (SyntaxWarning) - check/fix in a later job touching doctor.py.
- Job 16: stray demo serve processes PIDs 17456, 68768 could not be killed (permission denied); listed in human-test-items.md. Not retried.
