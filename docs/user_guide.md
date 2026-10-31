# Word Session user guide

Word Session remembers which Microsoft Word documents you had open, and where
your cursor was in each, so you can reopen them all with one click or one
command. It runs in your Windows account only; it needs no administrator
rights and no Python.

## Install

1. Run `WordSession-<version>-setup.exe`. It installs into
   `%LOCALAPPDATA%\Programs\WordSession` and adds a **Word Session** entry to
   the Start menu.
2. Tick **Start Word Session when I sign in** if you want the tray icon to
   appear after every login (you can change this later from the tray menu).

No installer? Unzip `WordSession-<version>-win64.zip` anywhere and run
`word-session-app.exe` from the folder.

## First run

Start **Word Session** from the Start menu. A small icon appears in the
notification area (click the `^` next to the clock if it is hidden) and the
manager opens in your web browser. The program works with the Word that is
running on your computer; it never needs to be signed in anywhere.

Tray icon, right-click menu:

| Item | What it does |
| --- | --- |
| Save session now | Saves the documents open in Word right now. |
| Restore latest session | Reopens the documents of the newest session. |
| Recent sessions | Restores one of the eight newest sessions. |
| Open manager | Opens the manager in your browser (also the default click on the icon). |
| Autosave | Turns the automatic background saves on or off. |
| Start at login | Starts Word Session when you sign in. |
| Open sessions folder / Open log | Opens the folder or log file in Explorer. |
| Quit | Stops Word Session. Word itself is left alone. |

The manager is only reachable from your own computer. If a browser tab says it
is signed out, choose **Open manager** from the tray again.

On the first run, sessions made by the older word-session tools are imported
automatically (see [Import old sessions](#import-old-sessions)).

## Save and restore a session

**From the tray:** choose *Save session now*, later *Restore latest session*
or pick a session under *Recent sessions*.

**From the manager:** the list shows every session with its documents. Open a
session to see its documents, rename it, pin it, edit its notes, or delete it, and restore it
with the *Restore* buttons.

**From the command line** (open a terminal in the install folder, or add it to
your `PATH`):

```text
word-session save --name "Thesis chapter 3"
word-session list
word-session restore            # the latest session
word-session restore thesis     # a name or id prefix
word-session current            # documents open in Word right now
```

Add `--json` to any command for machine-readable output. The old
`word-session-LoadSession.cmd` style shortcuts are still shipped.

Restoring never closes anything. Documents that are already open are left as
they are, and the document that was in front when you saved is opened last so
it ends up on top. Your cursor goes back to where it was; if the document has
changed so much that the position no longer exists, the page and line are
used instead.

Documents that were never saved ("Document1") cannot be reopened. They are
listed in the session, with a warning at save time, so you can see what was
not captured.

## Restore only some documents

In the manager, open the session, tick only the documents you want and press
*Restore selected*. From the command line use a pattern:

```text
word-session restore --only "*thesis*" --only "*.xlsx"
word-session restore --dry-run      # report what would open, open nothing
word-session restore --no-position  # do not move the cursor
```

A restore always tries every document. If some fail (file moved, locked, or
Word showed a dialog), the rest still open and you get a per-document report;
the command exits with code 4.

## Autosave and retention

While Word Session runs it saves your documents in the background every 10
minutes, but only if something changed (documents opened or closed, cursor
moved). Automatic sessions are marked *auto*; sessions you save yourself are
*manual* and are never deleted automatically.

Only the newest 20 automatic sessions are kept; older ones go to the `trash`
folder inside the sessions folder. Change the interval, the number kept, or
turn autosave off on the manager's *Settings* page, or with the *Autosave* tray
item. `word-session prune --keep 10` applies a limit by hand.

## Pinned sessions

A pinned session is protected from pruning, including an automatic session you
want to keep. Pin it from the manager or with `word-session pin <session>`
(`unpin` to undo).

## Where your files live

| What | Location |
| --- | --- |
| Sessions | `%APPDATA%\word-session\sessions\` |
| Settings | `%APPDATA%\word-session\config.toml` |
| Log | `%LOCALAPPDATA%\word-session\logs\word-session.log` |
| Deleted sessions | `trash` inside the sessions folder |
| The program | `%LOCALAPPDATA%\Programs\WordSession` |

Each session is one small text file (see `session_format.md`) that you can
copy, back up, or sync. Deleting a session in the manager moves it to
`trash`; restore it by moving the file back. You can point `sessions_dir` in
`config.toml` at a folder of your choice, for example one that you back up.

## Import old sessions

Word Session looks for sessions of the previous tools in `~\.word-session\`
and `~\.word-sessions\` the first time it runs, and copies them in as
*imported* sessions. The original files are never changed. To import again, or
from another folder:

```text
word-session import-legacy
word-session import-legacy D:\old\sessions
```

## Troubleshooting

**Run the checks first.**

```text
word-session doctor
```

It lists whether Word is installed and running, whether Word Session runs with
the same privileges as Word, and whether the sessions folder and settings can
be read and written. Lines marked `warn` or `FAIL` say what to fix.

**"Word is not responding."** Word is busy or showing a dialog (for example a
"Save changes?" question or a file-recovery pane). Switch to Word, close the
dialog, and try again. Restoring waits up to 60 seconds per document by
default.

**"Word is not running" although Word is open.** Word registers itself for
other programs only after it has had focus once or has a document open. Click
into a Word window or open a document, then retry. If Word Session or Word was
started "as administrator", the other cannot see it: start both normally, or
both as administrator. `doctor` reports an elevation mismatch.

**Files on OneDrive or SharePoint.** Documents opened from the cloud are saved
by their web address and reopened from it; this needs you to be signed in to
Office. Documents in a synced OneDrive folder behave as local files, but a
file that is "online only" may take a moment to download when it is restored.
A moved or renamed file is reported as missing instead of stopping the
restore.

**Unsaved documents are missing from a session.** A document that has never
been saved has no path, so it cannot be reopened. Save it in Word first.
Documents with unsaved changes are reopened from their last saved version.

**The icon is missing from the tray.** Open the manager through the Start
menu entry; if nothing happens, run `word-session open`, and check the log
(*Open log* in the tray menu, or the path above).

## Uninstall

Use **Settings, Apps, Installed apps, Word Session, Uninstall** (or the
Start menu entry). The uninstaller stops the running program and removes the
program folder and the start-at-login entry. **Your sessions and settings are
not deleted**; remove `%APPDATA%\word-session` and
`%LOCALAPPDATA%\word-session` by hand if you want them gone.
