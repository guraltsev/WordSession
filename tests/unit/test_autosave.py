"""Tests for the background ``Autosaver`` (injected waits; real waits stay under 0.5 s)."""

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from word_session.autosave import Autosaver
from word_session.config import Settings
from word_session.events import EventBus
from word_session.model import Position, Session
from word_session.service import SessionService
from word_session.word.fake import FakeWordBackend


class StubService:
    """Minimal service double: settings, events and a scripted ``autosave_tick``."""

    def __init__(self) -> None:
        self.settings = Settings()
        self.events = EventBus()
        self.ticks = 0
        self.action: Callable[[], None] = lambda: None

    def autosave_tick(self) -> Session | None:
        self.ticks += 1
        self.action()
        return None


def _run_loops(service: StubService, loops: int) -> tuple[Autosaver, list[float]]:
    """Run ``loops`` waits through an injected sleep and return the waits."""
    waits: list[float] = []
    done = threading.Event()

    def sleep(seconds: float) -> bool:
        if len(waits) >= loops:
            done.set()
            return True
        waits.append(seconds)
        return False

    saver = Autosaver(service, sleep=sleep)  # pyright: ignore[reportArgumentType]
    saver.start()
    assert done.wait(2)
    saver.stop()
    return saver, waits


def test_disabled_never_ticks() -> None:
    service = StubService()
    service.settings.autosave.enabled = False
    _run_loops(service, 3)
    assert service.ticks == 0


def test_enabled_ticks_each_loop_and_reads_interval_fresh() -> None:
    service = StubService()
    seen: list[int] = []

    def change_interval() -> None:
        seen.append(service.settings.autosave.interval_minutes)
        service.settings.autosave.interval_minutes = 2

    service.action = change_interval
    _, waits = _run_loops(service, 3)
    assert service.ticks == 3
    assert waits == [600.0, 120.0, 120.0]


def test_trigger_wakes_the_loop_and_stop_ends_it() -> None:
    service = StubService()
    ticked = threading.Event()
    service.action = ticked.set
    saver = Autosaver(service)  # pyright: ignore[reportArgumentType]
    saver.start()
    assert not ticked.wait(0.05)
    saver.trigger()
    assert ticked.wait(0.5)

    started = time.monotonic()
    saver.stop()
    assert time.monotonic() - started < 0.5
    assert not any(t.name == "autosave" for t in threading.enumerate())


def test_backoff_doubles_caps_and_resets() -> None:
    service = StubService()
    outcomes = iter(["fail", "fail", "fail", "fail", "ok", "ok"])

    def act() -> None:
        if next(outcomes) == "fail":
            service.events.publish({"type": "autosave_failed", "message": "boom"})

    service.action = act
    saver, waits = _run_loops(service, 6)
    base = 600.0
    assert waits == [base, 2 * base, 4 * base, 4 * base, 4 * base, base]
    assert saver.last_error is None


def test_last_error_is_kept_until_success() -> None:
    service = StubService()
    service.action = lambda: service.events.publish({"type": "autosave_failed", "message": "boom"})
    saver, _ = _run_loops(service, 1)
    assert saver.last_error == "boom"


def test_unexpected_exception_does_not_kill_the_thread() -> None:
    service = StubService()

    def explode() -> None:
        raise RuntimeError("kaput")

    service.action = explode
    saver, waits = _run_loops(service, 3)
    assert service.ticks == 3
    assert waits == [600.0, 1200.0, 2400.0]
    assert saver.last_error is not None and "kaput" in saver.last_error


def test_integration_with_fake_backend(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    service.settings.autosave.keep = 2
    steps: list[Callable[[], None]] = [
        lambda: None,
        lambda: None,
        lambda: setattr(fake_backend.documents[0], "position", Position(start=5, end=5)),
        lambda: setattr(fake_backend.documents[0], "position", Position(start=6, end=6)),
        lambda: setattr(fake_backend.documents[0], "position", Position(start=7, end=7)),
    ]
    calls: list[Any] = []

    def sleep(seconds: float) -> bool:
        # Mutate Word between ticks, then stop when the script is exhausted.
        if len(calls) == len(steps):
            return True
        steps[len(calls)]()
        calls.append(seconds)
        return False

    saver = Autosaver(service, sleep=sleep)
    saver.start()
    saver._thread.join(2)  # pyright: ignore[reportOptionalMemberAccess]
    saver.stop()

    # Tick 1 saves, tick 2 is unchanged, ticks 3-5 change; keep=2 prunes to two.
    autos = service.list_sessions(kind="auto")
    assert len(autos) == 2
    assert saver.last_saved_id == autos[0].id
    assert saver.last_error is None


def test_integration_unchanged_ticks_create_one_session(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    ticks = [0]

    def sleep(seconds: float) -> bool:
        ticks[0] += 1
        return ticks[0] > 2

    saver = Autosaver(service, sleep=sleep)
    saver.start()
    saver._thread.join(2)  # pyright: ignore[reportOptionalMemberAccess]
    saver.stop()
    assert len(service.list_sessions(kind="auto")) == 1
    _ = pytest, fake_backend
