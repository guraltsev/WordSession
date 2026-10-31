"""Shared pytest fixtures and marker handling for the Word Session tests."""

import os
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from word_session.config import Settings
from word_session.service import SessionService
from word_session.store import SessionStore
from word_session.word.fake import FakeDocument, FakeWordBackend
from word_session.word.worker import ComWorker


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``WORD_SESSION_HOME`` at a fresh temporary directory for every test."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("WORD_SESSION_HOME", str(home))
    return home


@pytest.fixture
def fake_backend() -> FakeWordBackend:
    """Return a fake Word with ``a.docx`` and ``b.docx`` open (``b`` active)."""
    return FakeWordBackend(
        documents=[FakeDocument(path=r"C:\Docs\a.docx"), FakeDocument(path=r"C:\Docs\b.docx")]
    )


@pytest.fixture
def worker(fake_backend: FakeWordBackend) -> Iterator[ComWorker]:
    """Return a started worker around ``fake_backend``, stopped at teardown."""
    w = ComWorker(lambda: fake_backend, call_timeout=2)
    w.start()
    yield w
    w.stop()


@pytest.fixture
def fixed_clock() -> Callable[[], datetime]:
    """Return a clock yielding aware datetimes one minute apart from 2026-01-02 03:04:05 UTC."""
    current = [datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)]

    def clock() -> datetime:
        value = current[0]
        current[0] = value + timedelta(minutes=1)
        return value

    return clock


@pytest.fixture
def service(
    worker: ComWorker, isolated_home: Path, fixed_clock: Callable[[], datetime]
) -> SessionService:
    """Return a service over the fake worker; paths containing ``missing`` do not exist."""
    return SessionService(
        SessionStore(isolated_home / "sessions"),
        worker,
        Settings(),
        clock=fixed_clock,
        host="testhost",
        path_exists=lambda p: "missing" not in p,
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip tests that need real Word, a shared Word or a browser unless enabled."""
    on_windows = sys.platform == "win32"
    # Each marker is paired with the environment switch that enables it.
    rules = [
        (
            "word",
            on_windows and os.environ.get("WORD_SESSION_TEST_WORD") == "1",
            "needs WORD_SESSION_TEST_WORD=1 on Windows",
        ),
        (
            "shared_word",
            on_windows and os.environ.get("WORD_SESSION_TEST_SHARED_WORD") == "1",
            "needs WORD_SESSION_TEST_SHARED_WORD=1 on Windows",
        ),
        ("ui", os.environ.get("WORD_SESSION_TEST_UI") == "1", "needs WORD_SESSION_TEST_UI=1"),
    ]
    for marker, enabled, reason in rules:
        if enabled:
            continue
        skip = pytest.mark.skip(reason=reason)
        for item in items:
            if marker in item.keywords:
                item.add_marker(skip)
