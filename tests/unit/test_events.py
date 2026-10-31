"""Tests for ``EventBus``."""

import logging

import pytest

from word_session.events import Event, EventBus


def test_publish_reaches_all_subscribers_in_order() -> None:
    bus = EventBus()
    seen: list[str] = []
    bus.subscribe(lambda e: seen.append("a:" + e["type"]))
    bus.subscribe(lambda e: seen.append("b:" + e["type"]))
    bus.publish({"type": "x"})
    assert seen == ["a:x", "b:x"]


def test_unsubscribe_stops_delivery_and_is_idempotent() -> None:
    bus = EventBus()
    seen: list[Event] = []
    unsubscribe = bus.subscribe(seen.append)
    bus.publish({"type": "one"})
    unsubscribe()
    unsubscribe()
    bus.publish({"type": "two"})
    assert [e["type"] for e in seen] == ["one"]


def test_failing_callback_is_logged_and_others_still_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = EventBus()
    seen: list[Event] = []

    def boom(event: Event) -> None:
        raise RuntimeError("nope")

    bus.subscribe(boom)
    bus.subscribe(seen.append)
    with caplog.at_level(logging.ERROR):
        bus.publish({"type": "x"})
    assert len(seen) == 1
    assert "event callback failed" in caplog.text


def test_callback_may_unsubscribe_itself_while_called() -> None:
    bus = EventBus()
    seen: list[str] = []
    holder: list[object] = []

    def once(event: Event) -> None:
        seen.append(event["type"])
        unsubscribe = holder[0]
        assert callable(unsubscribe)
        unsubscribe()

    holder.append(bus.subscribe(once))
    bus.publish({"type": "a"})
    bus.publish({"type": "b"})
    assert seen == ["a"]
