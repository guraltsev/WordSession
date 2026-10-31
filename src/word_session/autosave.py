"""Background autosave: snapshot the Word session at a configurable interval.

``Autosaver(service).start()`` runs one daemon thread named ``autosave`` that
calls ``service.autosave_tick()`` every ``settings.autosave.interval_minutes``
while autosave is enabled. Failures slow the loop down (up to four times the
interval) and are exposed through ``last_error``.
"""

import logging
import threading
from collections.abc import Callable

from word_session.events import Event
from word_session.service import SessionService

_log = logging.getLogger(__name__)

_MAX_BACKOFF = 4  # longest wait, as a multiple of the configured interval


class Autosaver:
    """Run automatic saves of ``service`` on a background thread.

    Parameters
    ----------
    service : SessionService
        Service whose ``autosave_tick`` is called and whose settings are read
        fresh on every loop.
    sleep : Callable[[float], bool] or None
        Replaces the interruptible wait in tests. It receives the number of
        seconds to wait and returns ``True`` when the loop should stop.

    Attributes
    ----------
    last_error : str or None
        Message of the latest autosave failure; cleared by the next success.
    last_saved_id : str or None
        Id of the session saved by the most recent successful tick that
        saved something.

    Methods
    -------
    start
        Start the background thread.
    stop
        Stop the thread and wait for it.
    trigger
        Wake the loop so a tick runs soon.
    """

    def __init__(
        self,
        service: SessionService,
        *,
        sleep: Callable[[float], bool] | None = None,
    ) -> None:
        self._service = service
        self._sleep = sleep if sleep is not None else self._wait
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_error: str | None = None
        self._last_saved_id: str | None = None
        self._failed_during_tick = False
        self._multiplier = 1
        self._unsubscribe: Callable[[], None] | None = None

    @property
    def last_error(self) -> str | None:
        """Return the latest failure message, or None after a success."""
        with self._lock:
            return self._last_error

    @property
    def last_saved_id(self) -> str | None:
        """Return the id of the latest session this autosaver saved."""
        with self._lock:
            return self._last_saved_id

    def start(self) -> None:
        """Start the ``autosave`` daemon thread; does nothing if running."""
        if self._thread is not None and self._thread.is_alive():
            return

        # Listen for failures published by the service during ticks.
        self._stop.clear()
        self._wake.clear()
        self._unsubscribe = self._service.events.subscribe(self._on_event)
        self._thread = threading.Thread(target=self._run, name="autosave", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the thread, waiting up to ``timeout`` seconds for it to end."""
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        self._thread = None
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def trigger(self) -> None:
        """Wake the loop so a tick runs soon (after a settings change)."""
        self._wake.set()

    # ---- internals ----

    def _run(self) -> None:
        """Loop: wait, tick, adjust the backoff; never raise."""
        while not self._stop.is_set():
            # Wait the (possibly backed-off) interval; a True answer means stop.
            interval = self._service.settings.autosave.interval_minutes * 60.0
            if self._sleep(interval * self._multiplier) or self._stop.is_set():
                return

            # Run the tick and turn its outcome into backoff state.
            self._failed_during_tick = False
            try:
                self._tick()
            except Exception as exc:
                _log.warning("autosave tick crashed", exc_info=True)
                self._record_failure(f"{type(exc).__name__}: {exc}")
            else:
                if not self._failed_during_tick:
                    self._multiplier = 1
                    with self._lock:
                        self._last_error = None

    def _tick(self) -> None:
        """Save once if autosave is enabled."""
        if not self._service.settings.autosave.enabled:
            return
        session = self._service.autosave_tick()
        if session is not None:
            with self._lock:
                self._last_saved_id = session.id

    def _wait(self, seconds: float) -> bool:
        """Wait for the interval, a trigger or stop; return True to stop."""
        self._wake.wait(seconds)
        self._wake.clear()
        return self._stop.is_set()

    def _on_event(self, event: Event) -> None:
        """Record ``autosave_failed`` events published by the service."""
        if event.get("type") == "autosave_failed":
            self._failed_during_tick = True
            self._record_failure(str(event.get("message", "Autosave failed")))

    def _record_failure(self, message: str) -> None:
        """Remember the error and double the next wait (capped)."""
        with self._lock:
            self._last_error = message
        self._multiplier = min(self._multiplier * 2, _MAX_BACKOFF)
