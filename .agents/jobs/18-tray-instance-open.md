# Job 18 — Tray app, single instance, `open`, start at login

Depends on: 16
Plan reference: §3.9 (process model, tray menu), §6 Phase 5
Decisions: D3

## Goal

Ship the long-running app: one process per user that owns the Word worker
and the server, shows a tray icon, and opens the manager in the default
browser — from the tray, from `word-session open`, or by launching the app
again.

## Files

- `pyproject.toml` (runtime deps `pystray>=0.19`, `Pillow>=10`)
- `src/word_session/instance.py`, `src/word_session/tray.py`,
  `src/word_session/autostart.py`, `src/word_session/app.py`
- `src/word_session/web/app.py` (add `/api/internal/shutdown` only)
- `src/word_session/cli.py` (add `app`, `open`; implement `app_main`)
- `packaging/icons/` (icon generator script + generated PNG/ICO, see below)
- `src/word_session/assets/` (copies of the tray PNGs)
- `tests/unit/test_instance.py`, `tests/unit/test_autostart.py`,
  `tests/unit/test_app.py`, `tests/cli/test_open.py`

## Contract — `instance.py`

```python
@dataclass
class InstanceInfo:
    pid: int
    port: int
    secret: str          # Auth.instance_secret
    version: str

class InstanceLock:      # named mutex "Local\WordSession.App" on Windows
    def acquire(self) -> bool: ...   # False if another instance holds it
    def release(self) -> None: ...

def write_instance(path: Path, info: InstanceInfo) -> None: ...   # atomic, UTF-8 JSON
def read_instance(path: Path) -> InstanceInfo | None: ...         # None if missing/invalid
def clear_instance(path: Path, pid: int) -> None: ...            # only if it is ours
def request_login_url(info: InstanceInfo, *, timeout: float = 3.0) -> str: ...
```

- `InstanceLock` on Windows: `win32event.CreateMutex(None, False, name)` +
  `GetLastError() == ERROR_ALREADY_EXISTS` → not acquired. Elsewhere (tests
  on Linux): an exclusive lock file next to the instance file
  (`msvcrt`/`fcntl` not required — use `os.open(..., O_CREAT | O_EXCL)` and
  remove on release; stale file with dead pid is taken over).
- `request_login_url`: POST `http://127.0.0.1:<port>/api/internal/login-code`
  with `Host` correct and `X-Word-Session-Secret`, using `urllib.request`
  (no extra deps); returns the URL; raises `ConnectionError` on failure.
- The instance file is written only after the server is up and removed on
  clean exit.

## Contract — `autostart.py`

```python
def is_enabled() -> bool: ...
def enable(command: str) -> None: ...
def disable() -> None: ...
def app_command() -> str: ...   # quoted path to word-session-app(.exe), or "<python> -m word_session app"
```

`HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`, value
name `WordSession`. On non-Windows: `is_enabled()` False, others raise
`NotImplementedError`. Tests monkeypatch a fake `winreg` object.
`app_command()` uses `sys.frozen`/`sys.executable` to find the
`word-session-app.exe` next to the running exe when frozen.

## Contract — `app.py`

```python
class App:
    def __init__(self, *, fake: bool = False, open_browser: bool = False) -> None: ...
    def run(self) -> int: ...          # blocks until quit
    def open_manager(self) -> None: ...
    def quit(self) -> None: ...
```

`run`:

1. `InstanceLock.acquire()`; if held by another instance: read the
   instance file, `request_login_url`, `webbrowser.open`, return 0. If that
   fails, show a message box (`ctypes.windll.user32.MessageBoxW`, guarded)
   "Word Session is already running but not responding" and return 1.
2. `configure_logging`, `open_service(fake=...)`, `first_run_import`,
   `start_server`, `write_instance`.
3. Apply `settings.ui.start_at_login` to `autostart` (enable/disable to
   match) — failures logged, not fatal.
4. Build the tray (`tray.py`) and run it on the **main thread**
   (`icon.run()`); server and worker stay on their threads.
5. `open_browser=True` (used when launched from the Start menu) → open the
   manager once the icon is up.
6. On quit: stop tray, server, service; `clear_instance`; release lock.

`open_manager`: mint a login code via the handle's `auth`, `webbrowser.open`.
Opening never invalidates other tabs.

`/api/internal/shutdown` (POST, instance-secret protected like the
login-code endpoint): calls the registered quit callback; used by tests and
by the installer (job 21) to stop a running instance before upgrading. Add
an optional keyword parameter `on_shutdown: Callable[[], None] | None = None`
to `create_app` and `start_server` (404 for the route when `None`); `App`
passes `self.quit`.

## Contract — `tray.py`

```python
def build_icon(app: App, service: SessionService) -> pystray.Icon: ...
```

Menu (plan §3.9), items calling the service on a background thread so the
tray never blocks:

- "Save session now" → `capture()`; notify "Saved N documents" or the
  warning/error.
- "Restore latest session" → `restore("latest")`; notify the summary;
  failures listed.
- "Recent sessions" submenu: pinned first, then newest, max 8; click
  restores. Rebuilt when sessions change (subscribe to `EventBus`; call
  `icon.update_menu()`).
- "Open manager…" (default item, also on double-click).
- separator; "Autosave" checkable (bound to `settings.autosave.enabled`,
  persisted with `save_settings`); "Start at login" checkable (autostart +
  settings).
- "Open sessions folder", "Open log" (`os.startfile`, guarded).
- separator; "Quit".

Icon states: `idle`, `working` (while a capture/restore runs), `warning`
(last autosave failed or Word not responding — cleared by the next
success). Notifications via `icon.notify(...)`.

Icons: generate simple 64×64 PNGs (a page shape with a bookmark; three
colour variants) with Pillow in a script `packaging/icons/make_icons.py`,
commit the PNGs and a multi-size `app.ico`. Load them via
`importlib.resources` from `src/word_session/assets/` (copy the PNGs there).

## CLI

- `word-session app [--open]` → `App(fake=args.demo, open_browser=args.open).run()`.
- `app_main()` (gui-script entry) → `raise SystemExit(main(["app", "--open"]))`.
- `word-session open`: read instance file; if an instance answers,
  `request_login_url` + `webbrowser.open`, exit 0; otherwise start the app
  detached (`subprocess.Popen([...app_command...], creationflags=DETACHED_PROCESS
  | CREATE_NEW_PROCESS_GROUP)` on Windows) with `--open`, exit 0; print the
  URL in either case when it is known.

## Tests

- instance: write/read/clear (incl. invalid JSON, other pid), lock
  acquire/release and second acquire fails (lock-file implementation),
  `request_login_url` against a real `start_server` with the demo service.
- autostart with fake `winreg`; `app_command` frozen vs. not.
- app: `App(fake=True)` with `pystray.Icon` monkeypatched by a fake whose
  `run()` returns immediately after calling a hook — assert server started,
  instance file written, then cleaned up; second-instance path opens the
  browser via the first instance's endpoint (monkeypatch `webbrowser.open`).
- tray menu built from sessions (fake icon), recent ordering, callbacks
  invoke the service (no real tray).
- `open` command both branches (monkeypatch `subprocess.Popen`).

## Acceptance

README rule 7 commands. Manually: `uv run word-session --demo app --open` →
tray icon appears, manager opens; run `uv run word-session --demo open` in
another terminal → a new tab opens and the old one keeps working; "Quit"
removes the icon and the instance file.
