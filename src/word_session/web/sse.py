"""Server-sent events stream bridging the service event bus to HTTP clients.

``event_stream(bus)`` yields SSE frames for one client: a ``hello`` event on
connect, one frame per bus event and a keepalive comment while idle.
"""

import asyncio
import contextlib
import json
from collections.abc import AsyncGenerator

from word_session.events import Event, EventBus


async def event_stream(bus: EventBus, *, keepalive: float = 15.0) -> AsyncGenerator[str]:
    """Yield SSE frames for one connected client until it disconnects.

    Parameters
    ----------
    bus : EventBus
        Bus whose events are forwarded; every stream receives every event.
    keepalive : float
        Seconds of silence before a ``: keepalive`` comment is sent.

    Yields
    ------
    str
        Complete SSE frames: ``event: hello`` first, then
        ``event: <type>`` / ``data: <json>`` for each bus event.

    Notes
    -----
    The stream subscribes before yielding ``hello``, so no event published
    after a client sees ``hello`` is missed. It unsubscribes when closed.
    """
    # Events arrive on arbitrary threads; hand them to this loop's queue.
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Event] = asyncio.Queue()

    def forward(event: Event) -> None:
        # A closed loop means the client is gone; drop the event.
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(queue.put_nowait, event)

    unsubscribe = bus.subscribe(forward)
    try:
        yield "event: hello\ndata: {}\n\n"
        # Alternate between waiting for an event and signalling liveness.
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=keepalive)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            data = json.dumps(event, default=str)
            yield f"event: {event.get('type', 'message')}\ndata: {data}\n\n"
    finally:
        unsubscribe()
