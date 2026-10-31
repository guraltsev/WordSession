# Legacy scripts

Read-only reference material from before the migration to the
`word_session` package. Do not extend these files.

- `python/` — the first Python implementation. `word-session.py` is the last
  working Python version (CLI with `save` / `load`); `word_session_lib.py` is
  its COM helper module, `word-session.spec` the PyInstaller spec, and
  `word-session-examples.py` scratch cells exercising the library.
- `powershell/` — the older PowerShell implementation (`word-session.ps1`)
  and its three `.cmd` wrappers. It uses a different file format and
  directory.
- `wx-prototype/` — a wxPython list-with-checkboxes UI prototype with dummy
  data; kept only as a UI reference.

These files are kept until job 22 (decommissioning). The full original tree
is available at the git tag `legacy-baseline`.
