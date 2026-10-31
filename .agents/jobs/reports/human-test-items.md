
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
