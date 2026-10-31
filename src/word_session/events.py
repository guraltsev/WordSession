"""A small synchronous publish/subscribe bus for service events.

Create an ``EventBus``, register callbacks with ``subscribe`` and deliver
events with ``publish``. Callbacks run on the publishing thread; a failing
callback is logged and never prevents the others from running.
"""

import logging
import threading
from collections.abc import Callable
from typing import Any

Event = dict[str, Any]  # always has a "type" key

_log = logging.getLogger(__name__)


class EventBus:
    """Deliver events to subscribed callbacks on the publishing thread.

    Methods
    -------
    subscribe
        Register a callback and receive a function that unregisters it.
    publish
        Call every subscribed callback with an event.

    Notes
    -----
    Subscribing and unsubscribing are thread-safe. Callbacks are invoked from a
    snapshot, so they may subscribe or unsubscribe while being called.
    """

    def __init__(self) -> None:
        self._callbacks: list[Callable[[Event], None]] = []
        self._lock = threading.Lock()

    def subscribe(self, callback: Callable[[Event], None]) -> Callable[[], None]:
        """Register ``callback`` and return a function that unsubscribes it.

        Parameters
        ----------
        callback : Callable[[Event], None]
            Called with every published event.

        Returns
        -------
        Callable[[], None]
            Removes the subscription; calling it twice is harmless.
        """
        with self._lock:
            self._callbacks.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                # Remove by identity of this registration only once.
                if callback in self._callbacks:
                    self._callbacks.remove(callback)

        return unsubscribe

    def publish(self, event: Event) -> None:
        """Deliver ``event`` to every subscriber, logging callback failures.

        Parameters
        ----------
        event : Event
            The event dictionary; it must contain a ``"type"`` key.
        """
        # Snapshot under the lock, then call outside it so callbacks cannot deadlock.
        with self._lock:
            callbacks = list(self._callbacks)
        for callback in callbacks:
            try:
                callback(event)
            except Exception:
                _log.exception("event callback failed for %s", event.get("type"))
