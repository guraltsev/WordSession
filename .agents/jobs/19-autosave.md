# Job 19 — Autosave

Depends on: 18
Plan reference: §3.4 (autosave settings), §3.6 (`autosave_tick`), §6 Phase 5 step 2

## Goal

Snapshot the Word session in the background at a configurable interval,
only when something changed, without ever starting Word or interfering
with a restore.

## Files

- `src/word_session/autosave.py`
- `src/word_session/app.py` (start/stop the autosaver; wire tray state)
- `src/word_session/web/app.py` (only: apply interval changes on PUT settings, see below)
- `tests/unit/test_autosave.py`

## Contract

```python
class Autosaver:
    def __init__(self, service: SessionService, *,
                 sleep: Callable[[float], bool] | None = None) -> None: ...
    def start(self) -> None: ...
    def stop(self, timeout: float = 5.0) -> None: ...
    def trigger(self) -> None: ...           # run a tick soon (e.g. after settings change)
    @property
    def last_error(self) -> str | None: ...
    @property
    def last_saved_id(self) -> str | None: ...
```

## Behaviour

- One daemon thread `"autosave"`. Loop: wait the interval
  (`service.settings.autosave.interval_minutes`, read fresh every loop), via
  a `threading.Event.wait(timeout)` so `stop()` and `trigger()` wake it
  immediately. `sleep` injection replaces that wait in tests (returns
  `True` to stop).
- Each tick: if `settings.autosave.enabled` is false → skip. Else
  `service.autosave_tick()`. The service already handles "restore in
  progress", "Word not running", "no change", pruning, and publishes
  `autosave_failed`.
- Failure backoff: subscribe to `autosave_failed`; after a failure the next
  wait is doubled (max 4× the interval); a success resets it. Store the
  message in `last_error`, clear it on success.
- Never raises out of the thread; unexpected exceptions are logged and
  count as a failure.
- The `App` starts the autosaver after the server and stops it first on
  quit. The tray "Autosave" toggle and `PUT /api/settings` call `trigger()`
  so a new interval or enable state takes effect without waiting out the
  old interval (the web app gets an optional `on_settings_changed` callback
  in `create_app`; default no-op).
- Tray icon state: `warning` while `last_error` is set (subscribe to
  `autosave_failed` and `session_saved` events).

## Tests (no real time waits longer than ~0.5 s)

- disabled → `autosave_tick` not called;
- enabled → called each loop; interval read fresh each loop;
- `trigger()` wakes the loop early; `stop()` ends it promptly;
- backoff doubling and reset; cap at 4×;
- unexpected exception does not kill the thread;
- integration with the fake backend: two ticks with no change create one
  auto session; a position change creates a second; `keep` pruning applies.

## Acceptance

README rule 7 commands. Manually with `--demo app`: set interval 1 minute
in Settings, watch an `auto` session appear; toggle autosave off in the
tray, confirm no new ones.
