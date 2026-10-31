# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [2.0.0] - 2026-10-31

### Added

- Built-in user guide, served by the app at `/help.html` without sign-in and
  opened from the new **Help** item in the tray menu and the **Help** link in
  the manager's top bar.
- Tooltips on every button in the manager, and small **?** links next to
  buttons, headings and settings that open the matching section of the guide
  in a new tab.
- **Create Start menu shortcut** on the Settings page and
  `word-session shortcut [--remove]`: adds Word Session to the current
  user's own Start menu (no administrator rights).

- **Open now** page: tick documents, **Save selected as session…** (the ticks
  stay) and **Close now**. Close now never discards work: documents with
  unsaved changes stay open and are reported. API: `POST /api/word/close`
  and an optional `paths` list on `POST /api/sessions`.
- `README.md` and an MIT `LICENSE`.

### Fixed

- Word running with no document open (for example on its start screen) was
  reported as "Word not running"; it is now found and used.
- Opening Diagnostics no longer flashes a console window.

### Changed

- **Breaking:** the programs are renamed. The command-line program is now
  `word-session-cli` (was `word-session`) and the tray application, which
  opens the manager, is now `word-session` (was `word-session-app`). Update
  scripts, shortcuts and autostart entries; the Start menu shortcut and
  **Start at login** are rewritten when you save the settings again.
- Every heading, label, setting, column and button in the manager has a 2–4
  sentence tooltip.
- The user guide now lives in `src/word_session/web/static/help.html`;
  `docs/user_guide.md` points there.
- The build scripts moved to `_scripts/` (`build.cmd`, `build.ps1`,
  `smoke_test.ps1`).

### Removed

- Everything for the old tools: `word-session import-legacy`, the `serve
  --no-import` flag, the automatic first-run import, `/api/import-legacy`,
  the Settings button, the doctor `legacy` check and the `imported` session
  kind. Sessions of kind `imported` no longer load.
- The Inno Setup installer (`packaging/installer.iss`, `build.ps1
  -Installer`). Word Session ships as a zip only: unzip it anywhere and use
  the Start menu button.
- The `word-session-LoadSession.cmd`, `word-session-WriteSession.cmd` and
  `word-session-GetDocuments.cmd` shims of the old tools are no longer
  shipped; use `word-session restore`, `save` and `current`.

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
