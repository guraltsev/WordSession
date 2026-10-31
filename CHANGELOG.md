# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-10-31

First release of the rewritten Word Session. It replaces the Python v0 and
PowerShell scripts.

### Added

- Installable Python package with a `word-session` command: `save`,
  `restore` (alias `load`), `current`, `list`, `show`, `rename`, `delete`,
  `pin`, `unpin`, `notes`, `prune`, `diff`, `import-legacy`, `doctor`,
  `serve`, `app`, `open` and `quit-app`. Stable exit codes and `--json`
  output for scripting.
- Session file format v1 (`docs/session_format.md`): character-offset cursor
  positions with page and line as fallback, document location kinds, window
  state, notes, pinning, unknown-field preservation and atomic writes.
- Tray application with save, restore, recent sessions, autosave and
  start-at-login controls, notifications, and a single instance per user.
- Browser manager (local, token-protected) to browse, inspect, rename, pin,
  annotate, delete and partially restore sessions, and to change settings.
- Autosave with change detection and retention of the newest N automatic
  sessions; manual and pinned sessions are never pruned. Deleted sessions go
  to a `trash` folder.
- Automatic, non-destructive import of sessions from the old tools
  (`~\.word-session\` and `~\.word-sessions\`, including UTF-16 files).
- `doctor` diagnostics for Word, the Running Object Table, elevation, paths
  and the log.
- Per-user Windows packaging: PyInstaller bundle with `word-session.exe` and
  `word-session-app.exe`, a zip, an optional Inno Setup installer (no admin
  rights), and shims for the old `.cmd` entry points.
- User guide.

### Fixed

Defects of the legacy tools (migration plan section 1.2):

- The command-line tool no longer fails with a syntax error on start.
- Saving no longer activates every document, so the active window and window
  flashing are unchanged by a save.
- Not starting Word when it is not running is now honoured; the probe result is
  used and no hidden start can race in.
- Restore continues after a missing, moved or locked document and reports each
  document's outcome, instead of aborting on the first.
- Restore no longer hangs on modal dialogs: alerts are suppressed and Word
  calls time out with a clear "Word is not responding" error.
- Unsaved documents are recorded as such rather than as unopenable paths.
- Cloud (OneDrive/SharePoint) documents are recognised as URLs and no longer
  reported as missing.
- Cursor positions are stored as character offsets, with page and line only as
  a fallback.
- "Latest session" is chosen from session ids, not from file creation times of
  arbitrary files in the folder.
- The cursor goes to the right line (page and line, not an absolute line
  number) and `GetDocuments` does something.
- Restore reuses the running Word instead of always starting a new one.
- No dependency on the generated COM cache; late binding with fixed constants.
- Word being busy (`RPC_E_CALL_REJECTED`, `RETRYLATER`) is retried instead of
  failing.
- Logging and exit codes replace `print` and ignored return values; session
  files are written atomically as UTF-8.
- The code is importable and covered by automated tests.
