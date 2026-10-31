"""Run every Word call on one dedicated COM thread with timeouts and retries.

Create a ``ComWorker`` with a backend factory, ``start`` it (or use it as a
context manager) and run work with ``call`` or ``submit``. All backend calls
execute strictly one at a time on a thread named ``word-com``; callers wait
with a timeout, so a stuck Word cannot freeze the CLI, tray or web server.
Calls rejected with ``WordBusy`` are retried automatically.
"""

import logging
import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, TypeVar

from word_session.word.backend import WordBackend, WordBusy, WordError, WordNotResponding

T = TypeVar("T")

_log = logging.getLogger(__name__)

# Seconds slept between busy retries; the last value repeats indefinitely.
_BUSY_DELAYS = (0.1, 0.25, 0.5, 1.0, 2.0)

# Marker enqueued by ``stop`` to end the worker loop.
_SENTINEL = object()


class ComWorker:
    """Execute Word backend calls on one dedicated thread.

    Parameters
    ----------
    backend_factory : Callable[[], WordBackend]
        Creates the backend; invoked on the worker thread because COM objects
        belong to the thread that created them.
    call_timeout : float
        Seconds ``call`` waits by default, and the running time after which
        the worker counts as stuck.
    busy_retry_total : float
        Maximum total seconds slept while retrying a ``WordBusy`` failure.

    Attributes
    ----------
    is_stuck : bool
        True while the running job has exceeded ``call_timeout``.

    Methods
    -------
    start
        Launch the worker thread.
    stop
        Stop the thread, failing pending jobs and disconnecting the backend.
    submit
        Queue a job and return its future.
    call
        Run a job and wait for its result with a timeout.

    Raises
    ------
    RuntimeError
        From ``start`` when the worker was already started.

    Notes
    -----
    Re-entrant ``call``/``submit`` from the worker thread run directly. No COM
    message filter is installed; the retry loop covers rejected calls. A
    message filter is a possible later improvement.
    """

    def __init__(
        self,
        backend_factory: Callable[[], WordBackend],
        *,
        call_timeout: float = 30.0,
        busy_retry_total: float = 10.0,
    ) -> None:
        self._factory = backend_factory
        self._call_timeout = call_timeout
        self._busy_retry_total = busy_retry_total
        self._queue: queue.Queue[Any] = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._backend: WordBackend | None = None
        self._backend_error: BaseException | None = None
        self._stopping = False
        self._running_since: float | None = None

    # -- Public interface -----------------------------------------------------

    def start(self) -> None:
        """Launch the daemon worker thread named ``word-com``.

        Raises
        ------
        RuntimeError
            If the worker was already started.
        """
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("ComWorker already started")
            self._thread = threading.Thread(target=self._run, name="word-com", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the worker, failing pending jobs and disconnecting the backend.

        Parameters
        ----------
        timeout : float
            Seconds to wait for the thread to exit. A thread stuck in a Word
            call is abandoned (it is a daemon) and exits when the call returns.
        """
        # Mark stopping first so racing submits fail and queued jobs are
        # failed rather than run.
        with self._lock:
            thread = self._thread
            if thread is None or self._stopping:
                return
            self._stopping = True
        self._queue.put(_SENTINEL)
        thread.join(timeout)

    def submit(self, fn: Callable[[WordBackend], T]) -> Future[T]:
        """Queue ``fn`` for the worker thread and return its future.

        Parameters
        ----------
        fn : Callable[[WordBackend], T]
            Receives the backend and runs on the worker thread.

        Returns
        -------
        Future[T]
            Resolves to ``fn``'s result or its exception.

        Raises
        ------
        WordError
            If the worker is not running or was stopped.
        WordNotResponding
            If the worker is stuck in a previous job.
        """
        # Re-entrant use from the worker thread runs inline to avoid deadlock.
        future: Future[T] = Future()
        if threading.current_thread() is self._thread:
            self._execute(fn, future)
            return future

        # Refuse work that could never run promptly.
        with self._lock:
            if self._stopping:
                raise WordError("worker stopped")
            if self._thread is None:
                raise WordError("worker not started")
            if self._stuck_locked():
                raise WordNotResponding(self._not_responding_message(self._call_timeout))
            self._queue.put((fn, future))
        return future

    def call(self, fn: Callable[[WordBackend], T], *, timeout: float | None = None) -> T:
        """Run ``fn`` on the worker thread and wait for its result.

        Parameters
        ----------
        fn : Callable[[WordBackend], T]
            Receives the backend and runs on the worker thread.
        timeout : float | None
            Seconds to wait; defaults to ``call_timeout``.

        Returns
        -------
        T
            The value returned by ``fn``.

        Raises
        ------
        WordNotResponding
            If the wait expires (the job keeps running) or the worker is stuck.
        WordError
            If the worker is stopped, or whatever ``fn`` raised.
        """
        wait = self._call_timeout if timeout is None else timeout
        future = self.submit(fn)
        try:
            return future.result(wait)
        except FutureTimeoutError:
            # The job stays queued or running on the worker; only the wait ends.
            raise WordNotResponding(self._not_responding_message(wait)) from None

    @property
    def is_stuck(self) -> bool:
        """Return whether the running job has exceeded ``call_timeout``."""
        with self._lock:
            return self._stuck_locked()

    def __enter__(self) -> "ComWorker":
        """Start the worker and return it."""
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        """Stop the worker."""
        self.stop()

    # -- Worker thread --------------------------------------------------------

    def _run(self) -> None:
        """Serve queued jobs until the stop sentinel arrives."""
        # COM must be initialised on the thread that owns the COM objects.
        pythoncom: Any = None
        try:
            import pythoncom as _pythoncom  # pyright: ignore[reportMissingImports]

            pythoncom = _pythoncom
            pythoncom.CoInitialize()
        except ImportError:
            pythoncom = None

        try:
            # Create the backend here; a failing factory fails every job.
            try:
                self._backend = self._factory()
            except BaseException as exc:
                self._backend_error = exc

            # Serve jobs in submission order, failing those queued behind stop.
            while True:
                item = self._queue.get()
                if item is _SENTINEL:
                    break
                fn, future = item
                if self._stopping:
                    self._fail(future, WordError("worker stopped"))
                    continue
                self._execute(fn, future)
        finally:
            # Fail anything enqueued after the sentinel, then release Word.
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is not _SENTINEL:
                    self._fail(item[1], WordError("worker stopped"))
            if self._backend is not None:
                try:
                    self._backend.disconnect()
                except Exception:
                    _log.debug("backend disconnect failed", exc_info=True)
            if pythoncom is not None:
                pythoncom.CoUninitialize()

    def _execute(self, fn: Callable[[WordBackend], T], future: Future[T]) -> None:
        """Run one job with busy retry, tracking how long it has been running."""
        if not future.set_running_or_notify_cancel():
            return
        if self._backend is None:
            error = self._backend_error
            future.set_exception(error if error is not None else WordError("no backend"))
            return

        # Record the start time so ``is_stuck`` can see long-running jobs.
        reentrant = threading.current_thread() is self._thread and self._running_since is not None
        if not reentrant:
            with self._lock:
                self._running_since = time.monotonic()
        try:
            # Retry while Word reports busy, within the total sleep budget.
            slept = 0.0
            attempt = 0
            while True:
                try:
                    future.set_result(fn(self._backend))
                    return
                except WordBusy as exc:
                    delay = _BUSY_DELAYS[min(attempt, len(_BUSY_DELAYS) - 1)]
                    if slept + delay > self._busy_retry_total:
                        future.set_exception(exc)
                        return
                    _log.debug("Word busy; retrying in %.2f s", delay)
                    time.sleep(delay)
                    slept += delay
                    attempt += 1
                except BaseException as exc:
                    future.set_exception(exc)
                    return
        finally:
            if not reentrant:
                with self._lock:
                    self._running_since = None

    # -- Helpers --------------------------------------------------------------

    def _stuck_locked(self) -> bool:
        """Return whether the running job is over time (``_lock`` must be held)."""
        since = self._running_since
        return since is not None and time.monotonic() - since > self._call_timeout

    @staticmethod
    def _not_responding_message(seconds: float) -> str:
        """Build the user-facing timeout message."""
        return f"Word did not respond within {seconds:g} s; it may be showing a dialog"

    @staticmethod
    def _fail(future: Future[Any], error: Exception) -> None:
        """Fail a pending future unless it was cancelled."""
        if future.set_running_or_notify_cancel():
            future.set_exception(error)
