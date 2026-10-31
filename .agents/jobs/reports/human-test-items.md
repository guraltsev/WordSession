
## Job 12
1. In a console with real Word running and documents open: `uv run word-session save`, then close the documents and `uv run word-session restore`. Expected: documents reopen, exit code 0, cursors restored.
2. `uv run word-session current` with Word closed. Expected: `error: Word is not running`, exit code 3.

## Job 13
1. With real Word running, `uv run word-session doctor`. Expected: all `ok`, exit 0.
2. Start Word as administrator and run `doctor` from a normal console. Expected: `word-process` shows FAIL with the privilege-level message, exit 1.
3. With old `~/.word-session` files present and a fresh `WORD_SESSION_HOME`, `uv run word-session list`. Expected: stderr line `Imported N sessions from the old word-session tools.` once only.

## Job 09
1. After capturing via the CLI with a few documents open in Word, confirm the captured document order matches the order Word opened them (oldest first) and that the active document/cursor did not change while listing.
2. If shared-Word tests skip with the ROT reason, click away from Word once (or open a document) and rerun `WORD_SESSION_TEST_SHARED_WORD=1 uv run pytest -m shared_word`.

## Job 16
1. Run `uv run word-session --demo serve --open` with a temporary `WORD_SESSION_HOME`. Expected: the browser opens the Sessions page (empty list message), header shows "Word 16.0 running" (demo) with a green dot.
2. Click "Save current session" (with and without a name). Expected: toast, new row with the local creation time, kind badge "manual", 3 documents.
3. Open the row; rename it, pin it, edit and save notes. Expected: changes appear; the Sessions list reflects them.
4. Untick one document and use "Restore selected". Expected: progress panel with bar then per-document status badges ("already_open" in the demo). Use the list's "Restore" button: the detail page opens and restores all.
5. Copy the second login URL from a second `word-session ... serve` output, or reload the first tab; open a second tab at the same URL as a new login (run `serve` output link again is single use, so use `word-session open` once job 18 exists, or mint another code over `POST /api/internal/login-code`). In tab A rename a session; expected: tab B's list updates within about 0.5 s without reload. Then edit in A and save in a stale B detail page: expected toast "This session was changed in another tab; showing the latest version."
6. "Delete session": confirm dialog (Escape cancels, Delete moves to trash), returns to the list.
7. Stop the server (Ctrl+C) while the tab is open. Expected: red banner "Word Session is not running — reopen it from the tray". Restart `serve` on the same port (`--port N`) without logging in again: the banner clears and the page shows "Not signed in. Open the manager from the tray icon or run `word-session open`." (cookie is not valid for the new process).
8. Switch the OS to dark mode (and back): colours follow `prefers-color-scheme`; tab through every screen: focus outline is visible, all buttons reachable; narrow the window to 360 px: tables scroll horizontally, no page-wide overflow.
9. Settings: change the autosave interval, Save: toast "Settings saved."; enter 0 in "interval": the error toast names the field. "Import sessions from old tools" shows a count line.
10. Diagnostics: table of checks and the log tail show; "Copy report" then paste into a text editor: checks first, then log lines.
11. With real Word closed and `serve` without `--demo`: Open now shows "Word is not running." and the dot is red; "Restore" on a session with `--no-start` unset starts Word (existing behaviour).


## Housekeeping
- Two stray `word-session.exe --demo serve --no-import` processes (PIDs 17456, 68768 at the time) were left by the job 16 executor; the sandbox denied killing them. Stop them with Task Manager or `Stop-Process` if still running (demo backend, temp data dir, localhost only).

## Job 18
1. `uv run word-session --demo app --open`. Expected: a tray icon (white page with a blue bookmark) appears and the browser opens the manager signed in.
2. In another terminal run `uv run word-session --demo open`. Expected: a new tab opens signed in, the old tab keeps working, and no second tray icon appears.
3. Tray menu: double-click the icon (opens a tab). Check "Save session now" (balloon "Saved 3 documents"), "Recent sessions" (newest first, pinned first, click restores), and the "Autosave" and "Start at login" checkmarks (the second creates or removes the `WordSession` value under `HKCU\...\Run`). Check "Open sessions folder" and "Open log".
4. Choose "Quit". Expected: the icon disappears and `instance.json` is removed from the state folder.
5. Launch the app a second time with the first running, with the Start menu or `word-session-app`. Expected: the existing instance opens a tab and the second process exits silently.
6. Kill the app from Task Manager, then run `word-session open`. Expected: a stale instance file is ignored and the app starts and opens the manager.
7. Check that the three icon colours (blue, amber, red) look acceptable.


## Job 19
1. `word-session --demo app`, set interval 1 minute in Settings with a changing demo state: an `auto` session appears within about a minute.
2. Untick "Autosave" in the tray: no new `auto` sessions appear.

## Job 20
1. Run `packaging\build.ps1` (without `-NoSync`) on a clean checkout with nothing running from `.venv`. Expected: zip built.
2. Double-click `dist\WordSession\word-session-app.exe` (or a shortcut with `--demo`). Expected: tray icon appears and the manager opens in the browser with styling; quit from the tray menu.
3. Run `dist\WordSession\word-session-WriteSession.cmd` and `word-session-GetDocuments.cmd` with real Word open. Expected: session saved / documents listed; window pauses only on error.
4. Run `word-session-LoadSession.cmd` with no argument and with a session file path. Expected: latest / that session restored.
5. Check exe icon and Properties > Details (version 0.1.0) in Explorer.

