# Job 16 — Web UI and `serve`

Depends on: 15, 13
Plan reference: §3.8 (UI), §3.9 (multiple tabs, disconnect message)
Decisions: D3 (default browser)

## Goal

Build the session manager UI as static files served by the API, and a
`word-session serve` command to run API + UI without the tray.

## Files

- `src/word_session/web/static/index.html`, `app.css`, `js/api.js`,
  `js/app.js`, `js/views/*.js`, `favicon.svg`
- `src/word_session/cli.py` (add `serve`)
- `tests/api/test_static.py`, `tests/cli/test_serve.py`

## Constraints

- **No build step, no CDN, no frameworks.** Plain HTML, CSS, ES modules
  (`<script type="module">`). Everything must work offline and satisfy
  `Content-Security-Policy: default-src 'self'` — no inline scripts, no
  inline `style=""` attributes, no `eval`.
- Render untrusted text (paths, names, notes) only with `textContent` /
  `setAttribute`; never `innerHTML` with data.
- Every API call goes through `js/api.js`, which adds
  `X-Word-Session: 1`, `credentials: "same-origin"`, parses
  `{"error": {...}}` bodies into thrown `ApiError(status, type, message)`.
- Light and dark theme from `prefers-color-scheme` using CSS custom
  properties; visible focus outlines; all actions reachable by keyboard;
  form controls have labels. Layout works from 360 px wide upward.

## Screens (hash routing in `app.js`)

1. `#/sessions` (default) — "Save current session" button with optional
   name field; search box (`q`); filter chips for kind and pinned; table:
   name, created (local time), kind badge, documents, missing (highlighted
   if > 0), pin toggle, "Restore" button. Click a row → detail.
2. `#/sessions/<id>` — name (inline rename), notes (textarea, save
   button), metadata, document list with checkboxes (all checked by
   default), location badge, `exists` flag, position hint "p. 12, l. 7";
   buttons: "Restore selected" (sends `only` with the selected full paths),
   "Remove selected from session", "Delete session" (confirm dialog).
   Restore shows a progress panel fed by SSE `restore_progress` for that
   session, then the final report with per-document status.
3. `#/now` — live documents in Word (`/api/word/documents`), Word status
   line from `/api/word`, "Save as session…" button.
4. `#/settings` — form for `Settings` (autosave enabled/interval/keep/
   only-on-change, restore defaults and timeout, sessions dir, start at
   login), save → PUT; "Import sessions from old tools" button showing the
   summary.
5. `#/diagnostics` — doctor checks table, log tail (`/api/logs`),
   "Copy report" button (doctor + last 200 log lines to clipboard).

Global elements: header with navigation and Word status dot; toast area.

## Behaviour

- Open one `EventSource("/api/events")` per tab. On `session_saved`,
  `session_updated`, `session_deleted` refresh the affected view (debounce
  300 ms). Other tabs' changes therefore appear live.
- Edits send `If-Match` with the revision from the last GET. On `412`:
  reload the session and toast "This session was changed in another tab;
  showing the latest version."
- Any `401` → full-page message: "Not signed in. Open the manager from the
  tray icon or run `word-session open`." (no login form).
- `EventSource` error or failed fetch (network error) → banner "Word
  Session is not running — reopen it from the tray". Remove the banner if a
  later `/api/health` succeeds **and** an authenticated call succeeds; if
  that call returns 401 (app restarted) show the not-signed-in message.
- `503` → inline "Word is not running" with a hint; `504` → "Word is not
  responding — it may be showing a dialog."
- No polling except `/api/word` every 10 s while the tab is visible
  (`document.visibilityState`).

## `serve` command

```text
word-session serve [--port P] [--open] [--no-import]
```

`open_service(...)` (respects global `--demo`), first-run import unless
`--no-import`, `start_server(service, port=P or 0)`, mint a login code,
print `Word Session manager: <login url>` and "Press Ctrl+C to stop", open
the browser with `webbrowser.open(url)` when `--open`, block until
`KeyboardInterrupt`, then stop server and close service; exit 0.

## Tests

- `test_static.py`: `/` returns HTML; every file referenced by `index.html`
  and by `import` statements in `js/**/*.js` is served with the right
  content type (`text/javascript` for `.js`); a scan of all static files
  finds no `http://`/`https://` URLs (except in comments), no `innerHTML`
  assignment, no inline `<script>` without `src`, no `style="`.
- `test_serve.py`: run `main(["--demo", "serve", "--port", "0"])` in a
  thread with `webbrowser.open` monkeypatched and `start_server` wrapped to
  capture the handle; GET `/api/health`; then trigger shutdown by
  monkeypatching the blocking wait (e.g. inject an `Event`) — design the
  `serve` loop so it waits on a `threading.Event` that tests can set and
  `KeyboardInterrupt` also ends.

## Acceptance

README rule 7 commands, plus manually: `uv run word-session --demo serve --open`
with a temp `WORD_SESSION_HOME`; save, rename, pin, restore with progress,
delete; open a second tab via a second login URL and see changes appear
live in both. Describe what you checked in the report (screenshots
optional).
