
## Job 12
1. In a console with real Word running and documents open: `uv run word-session save`, then close the documents and `uv run word-session restore`. Expected: documents reopen, exit code 0, cursors restored.
2. `uv run word-session current` with Word closed. Expected: `error: Word is not running`, exit code 3.

## Job 13
1. With real Word running, `uv run word-session doctor`. Expected: all `ok`, exit 0.
2. Start Word as administrator and run `doctor` from a normal console. Expected: `word-process` shows FAIL with the privilege-level message, exit 1.
3. With old `~/.word-session` files present and a fresh `WORD_SESSION_HOME`, `uv run word-session list`. Expected: stderr line `Imported N sessions from the old word-session tools.` once only.
