
## Job 12
1. In a console with real Word running and documents open: `uv run word-session save`, then close the documents and `uv run word-session restore`. Expected: documents reopen, exit code 0, cursors restored.
2. `uv run word-session current` with Word closed. Expected: `error: Word is not running`, exit code 3.
