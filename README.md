# Word Session

Save the set of documents you have open in Microsoft Word, and reopen them
later with the cursor back where it was. Think of it as "restore my tabs" for
Word.

Windows only. Requires desktop Microsoft Word.

## What it does

- **Save a session**: records every open document (or just the ones you tick)
  with the cursor position in each.
- **Restore a session**: reopens the documents in Word and puts the cursors
  back. Missing, locked or failing files are reported, not fatal.
- **Autosave**: saves in the background at an interval you choose and keeps
  only the newest automatic sessions. Pinned and manual sessions are never
  removed.
- **Open now**: lists what is open in Word, lets you save a selection as a
  session and close those documents.
- **Browser manager**: a local web page to search, rename, pin, annotate and
  delete sessions, change settings and run diagnostics. Every control has a
  tooltip, and a built-in user guide is one click away (**Help**).
- **Tray icon and command line**: `word-session-cli save`, `restore`, `current`,
  `list`, `show`, `diff`, `prune`, `doctor` and more, with `--json` output and
  stable exit codes for scripting.

Sessions are small JSON files in `%APPDATA%\word-session\sessions`. Nothing
leaves your computer; the manager listens on `127.0.0.1` only.

## Installation

### Option 1: zip release

1. Download `WordSession-<version>-win64.zip` and unzip it anywhere.
2. Run `WordSession\word-session.exe`. The tray icon appears and the
   manager opens in your browser.
3. On the **Settings** page press **Create Start menu shortcut**, and tick
   **Start at login** if you want autosave to run all the time.

No administrator rights are needed.

### Option 2: from source

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```powershell
git clone <repository-url> WordSession
cd WordSession
uv sync
uv run word-session-cli app        # tray application and browser manager
uv run word-session-cli doctor     # check that Word can be reached
```

To build the zip yourself: `_scripts\build.cmd` (output in `dist\`).

## Development

```powershell
uv run pytest                  # tests that need no Word
uv run ruff check src tests
$env:WORD_SESSION_TEST_WORD = 1; uv run pytest   # also drive a real, hidden Word
```

Use `word-session-cli --demo serve --open` to try the manager against a fake Word.
See [CHANGELOG.md](CHANGELOG.md) for release notes.

## License

[MIT](LICENSE)
