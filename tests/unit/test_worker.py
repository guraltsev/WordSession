"""Tests for ``ComWorker`` using the fake backend."""

import threading
import time
from collections.abc import Iterator

import pytest

from word_session.word import worker as worker_module
from word_session.word.backend import WordBackend, WordBusy, WordError, WordNotResponding
from word_session.word.fake import FakeWordBackend
from word_session.word.worker import ComWorker


def _connected_fake() -> FakeWordBackend:
    """Build a fake backend that is already connected."""
    backend = FakeWordBackend()
    backend.connect(start_if_needed=False)
    return backend


@pytest.fixture
def fake() -> FakeWordBackend:
    return _connected_fake()


@pytest.fixture
def worker(fake: FakeWordBackend) -> Iterator[ComWorker]:
    with ComWorker(lambda: fake, call_timeout=5.0) as w:
        yield w


def _wait_until(predicate, limit: float = 3.0) -> bool:  # type: ignore[no-untyped-def]
    """Poll briefly for a condition that depends on the worker thread."""
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_result_returned(worker: ComWorker) -> None:
    assert worker.call(lambda b: b.is_running()) is True


def test_exception_propagates(worker: ComWorker) -> None:
    def boom(backend: WordBackend) -> None:
        raise WordError("kaput")

    with pytest.raises(WordError, match="kaput"):
        worker.call(boom)


def test_factory_and_fn_run_on_word_com_thread() -> None:
    factory_thread: list[str] = []

    def factory() -> WordBackend:
        factory_thread.append(threading.current_thread().name)
        return _connected_fake()

    with ComWorker(factory) as w:
        name = w.call(lambda b: threading.current_thread().name)
    assert name == "word-com"
    assert factory_thread == ["word-com"]


def test_order_preserved(worker: ComWorker) -> None:
    seen: list[int] = []
    futures = [worker.submit(lambda b, i=i: seen.append(i)) for i in range(10)]
    for f in futures:
        f.result(2)
    assert seen == list(range(10))


def test_start_twice_raises(worker: ComWorker) -> None:
    with pytest.raises(RuntimeError):
        worker.start()


def test_busy_retry_succeeds(monkeypatch: pytest.MonkeyPatch, fake: FakeWordBackend) -> None:
    monkeypatch.setattr(worker_module, "_BUSY_DELAYS", (0.001,))
    fake.busy_calls = 2
    with ComWorker(lambda: fake) as w:
        assert w.call(lambda b: b.info()).running is True
    assert fake.busy_calls == 0


def test_busy_retry_gives_up(monkeypatch: pytest.MonkeyPatch, fake: FakeWordBackend) -> None:
    monkeypatch.setattr(worker_module, "_BUSY_DELAYS", (0.01,))
    fake.busy_calls = 1000
    with ComWorker(lambda: fake, busy_retry_total=0.3) as w, pytest.raises(WordBusy):
        w.call(lambda b: b.info())
    # Roughly 0.3 / 0.01 retries were attempted, not an unbounded number.
    assert 1000 - fake.busy_calls <= 40


def test_default_delay_sequence() -> None:
    assert worker_module._BUSY_DELAYS == (0.1, 0.25, 0.5, 1.0, 2.0)


def test_timeout_stuck_and_recovery(fake: FakeWordBackend) -> None:
    hang = threading.Event()
    fake.hang = hang
    with ComWorker(lambda: fake, call_timeout=0.3) as w:
        with pytest.raises(WordNotResponding, match=r"did not respond within 0\.2 s"):
            w.call(lambda b: b.info(), timeout=0.2)
        # The job is still running; after call_timeout the worker is stuck.
        assert _wait_until(lambda: w.is_stuck)
        with pytest.raises(WordNotResponding):
            w.call(lambda b: b.info())
        with pytest.raises(WordNotResponding):
            w.submit(lambda b: b.info())
        # Releasing the hang lets the job finish and the worker recover.
        hang.set()
        assert _wait_until(lambda: not w.is_stuck)
        assert w.call(lambda b: b.info()).running is True


def test_reentrant_call(worker: ComWorker) -> None:
    def outer(backend: WordBackend) -> bool:
        return worker.call(lambda b: b.is_running())

    assert worker.call(outer) is True
    assert worker.call(lambda b: worker.submit(lambda b2: 7).result(0)) == 7


def test_stop_fails_pending_and_disconnects(fake: FakeWordBackend) -> None:
    release = threading.Event()
    w = ComWorker(lambda: fake)
    w.start()
    started = threading.Event()

    def blocker(backend: WordBackend) -> bool:
        started.set()
        return release.wait(2)

    running = w.submit(blocker)
    pending = w.submit(lambda b: b.info())
    assert started.wait(2)

    stopper = threading.Thread(target=w.stop)
    stopper.start()
    assert _wait_until(lambda: w._stopping)  # pyright: ignore[reportPrivateUsage]
    release.set()
    stopper.join(3)

    assert running.result(1) is True
    with pytest.raises(WordError, match="worker stopped"):
        pending.result(1)
    assert "disconnect" in fake.calls
    with pytest.raises(WordError, match="worker stopped"):
        w.call(lambda b: b.info())
    with pytest.raises(WordError, match="worker stopped"):
        w.submit(lambda b: b.info())


def test_stop_without_start_is_noop() -> None:
    w = ComWorker(_connected_fake)
    w.stop()
    with pytest.raises(WordError):
        w.call(lambda b: b.info())


def test_context_manager_stops(fake: FakeWordBackend) -> None:
    with ComWorker(lambda: fake) as w:
        w.call(lambda b: b.info())
    assert "disconnect" in fake.calls
    with pytest.raises(WordError, match="worker stopped"):
        w.call(lambda b: b.info())
