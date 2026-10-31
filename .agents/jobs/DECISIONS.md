# Design decisions

All decisions are settled (the human delegated them on 2026-10-31). Jobs
read their values from here. If a decision proves unworkable, the
coordinator switches to the listed alternative, updates the row with date
and reason, and logs it in `CHANGES.md`.

| # | Decision | Value | Alternative if it fails | Affects jobs |
| --- | --- | --- | --- | --- |
| D1 | Sessions directory | `platformdirs.user_data_dir("word-session", appauthor=False, roaming=True) / "sessions"` (`%APPDATA%\word-session\sessions`) | — | 07, 13 |
| D2 | Web stack | FastAPI + uvicorn, pydantic v2 | stdlib `ThreadingHTTPServer` + small router, same routes | 04, 15, 16 |
| D3 | Manager UI host | Default browser via `webbrowser.open`; no embedded window | — | 16, 18 |
| D4 | Python version | 3.13 (`requires-python = ">=3.13,<3.14"`) | 3.14 if 3.13 cannot be installed by `uv` | 02 |
| D5 | Distribution | PyInstaller onedir + zip; per-user Inno Setup installer if `iscc.exe` is available | zip only | 20, 21 |
| D6 | CLI framework | stdlib `argparse` | — | 12, 13 |
| D7 | Default branch | `main` | — | 00 |
| D8 | Run mode | Fully autonomous; human tests only at the end (job 23 handoff) | — | all |
