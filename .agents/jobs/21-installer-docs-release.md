# Job 21 — Installer, user documentation, release

Depends on: 20
Plan reference: §5 (installer), §6 Phase 6 steps 2–3
Decisions: D5
Not part of the autonomous run: tagging `v1.0.0` and publishing anything.
Those are left to the human (job 23 handoff).

## Goal

Make the tool installable per user without admin rights or Python, document
it for end users, and prepare the 1.0.0 release.

## Files

- `packaging/installer.iss`
- `packaging/build.ps1` (add optional installer step)
- `docs/user_guide.md`, `docs/session_format.md`, `CHANGELOG.md`
- `pyproject.toml` (version `1.0.0`)
- `src/word_session/cli.py` (add `quit-app` only), `tests/cli/test_quit_app.py`

## Do

1. Inno Setup script (`installer.iss`):
   - `PrivilegesRequired=lowest`, `DefaultDirName={localappdata}\Programs\WordSession`,
     `DisableProgramGroupPage=yes`, app name "Word Session", version from a
     `/DAppVersion=` define passed by `build.ps1`;
   - installs the whole `dist\WordSession` folder;
   - Start menu shortcut "Word Session" → `word-session-app.exe` (which
     opens the manager);
   - optional task "Start Word Session when I sign in" → write the same
     `HKCU\…\Run` value as `autostart.enable` (value name `WordSession`,
     quoted path to `word-session-app.exe`); remove the value on uninstall;
   - before install/uninstall: if `%LOCALAPPDATA%` instance file exists,
     call `word-session.exe` with a hidden internal command to stop the
     running instance. Add CLI command `word-session quit-app` (in
     `cli.py`, small: read instance file, POST `/api/internal/shutdown`,
     wait ≤ 5 s for the instance file to disappear; exit 0 if nothing was
     running) — this is the only code change in this job; add a CLI test;
   - uninstall leaves the sessions and config folders untouched and says
     so on the final page.
2. `build.ps1 -Installer`: if `iscc.exe` is found (PATH or the default Inno
   Setup install dir), build `dist/WordSession-<version>-setup.exe`;
   otherwise print how to install Inno Setup and skip.
3. `docs/user_guide.md` for end users (not developers): install, first
   run (what the tray icon does, where the manager opens), saving and
   restoring (tray, manager, CLI), partial restore, autosave and retention,
   pinned sessions, where files live (plan §3.4), importing old sessions,
   troubleshooting (`doctor`, "Word is not responding", admin/elevation
   mismatch, OneDrive paths, unsaved documents), uninstall. Short sections,
   task-oriented headings.
4. `docs/session_format.md`: the v1 format (plan §3.3) as a reference:
   every field, types, meaning, compatibility rules (extra fields
   preserved, `version` gating), legacy formats that are imported.
5. `CHANGELOG.md` (Keep a Changelog style) with a 1.0.0 entry summarising
   the features and the legacy defects fixed (plan §1.2).
6. Bump version to `1.0.0`. Do **not** tag.

## Acceptance

- `build.ps1 -Installer` produces the setup exe (or clearly skips).
- Automated (if the installer was built): silent per-user install into a
  temp dir (`setup.exe /VERYSILENT /SUPPRESSMSGBOXES /CURRENTUSER
  /DIR=<tmp> /TASKS=""` — start-at-login task **off**), check the files and
  that `<tmp>\word-session.exe --version` runs; start
  `word-session-app.exe` with `WORD_SESSION_HOME` set to a temp dir and
  `--demo`, run the installer again over it and check the instance was
  stopped (`quit-app`); silent uninstall (`unins000.exe /VERYSILENT`) and
  check the folder is gone and the temp `WORD_SESSION_HOME` is untouched.
  Record each check in the report.
- For final human testing: Start menu entry, start-at-login task,
  uninstall page text.
- README rule 7 commands pass.
