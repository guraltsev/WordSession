# Legacy fixtures

Synthetic files (no real user data) for `tests/unit/test_legacy.py`.

| File | Format | Notes |
| --- | --- | --- |
| `20241123T101500 word-session.json` | Python v0 | ASCII, two docs (second is UNC with line 0, page -1) |
| `20240102T030405 word-session-cp1252.json` | Python v0 | path contains an e-acute, encoded cp1252 |
| `20250301T080910-Word-session.json` | PowerShell | UTF-16 LE with BOM, CRLF, list of two docs |
| `powershell_single.json` | PowerShell | `sessions` is one object; no timestamp in name (mtime fallback) |
| `20250302T111213-Word-session-utf8.json` | PowerShell | UTF-8 without BOM |
| `truncated.json` | invalid | truncated JSON |
| `unknown.json` | invalid | valid JSON, unknown keys |
| `v1.json` | version 1 | valid current-format session |
