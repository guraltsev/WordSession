"""Fixtures that run the real CLI against private invisible Word processes."""

import argparse
import importlib.util
import json
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from word_session.cli import main
from word_session.config import Settings
from word_session.model import DocumentState
from word_session.service import SessionService
from word_session.store import SessionStore
from word_session.word.com import ComWordBackend
from word_session.word.worker import ComWorker

_ROOT = Path(__file__).resolve().parents[2]
_CALL_TIMEOUT = 60.0


def load_make_docs() -> ModuleType:
    """Import ``scripts/make_test_docs.py`` (the scripts folder is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "make_test_docs", _ROOT / "scripts" / "make_test_docs.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def local_state(path: Path) -> DocumentState:
    """Return a minimal local document state for ``path``."""
    return DocumentState(path=str(path), location="local")


def _pid(backend: Any) -> int | None:
    """Return the process id of the Word a backend drives."""
    return load_make_docs().word_pid(backend._app)


class _KeepAliveService(SessionService):
    """A service whose ``close`` is a no-op so one Word survives many CLI runs."""

    def close(self) -> None:
        """Do nothing; the fixture stops the worker at teardown."""

    def really_close(self) -> None:
        """Stop the worker and thereby quit the private Word."""
        super().close()


class WordHarness:
    """Run CLI commands against one private Word and poke that Word directly."""

    def __init__(self, service: _KeepAliveService, worker: ComWorker) -> None:
        self.service = service
        self.worker = worker

    def run(self, *argv: str) -> int:
        """Run ``main`` with the shared service and return the exit code."""

        def factory(_: argparse.Namespace) -> SessionService:
            return self.service

        return main(list(argv), service_factory=factory)

    def app_call(self, fn: Callable[[Any], Any]) -> Any:
        """Run ``fn(application)`` on the COM thread and return its result."""
        return self.worker.call(lambda backend: fn(backend._app))  # type: ignore[attr-defined]

    def open_paths(self) -> list[str]:
        """Return the full names of the open documents."""
        return self.app_call(
            lambda app: [
                str(app.Documents.Item(i).FullName) for i in range(1, app.Documents.Count + 1)
            ]
        )

    def active_path(self) -> str:
        """Return the active document's full name."""
        return self.app_call(lambda app: str(app.ActiveDocument.FullName))

    def open_docs(self, *paths: Path) -> None:
        """Open the given documents in order (the last one ends up active)."""
        for path in paths:
            self.worker.call(lambda b, p=path: b.open_document(local_state(p)))

    def add_unsaved(self) -> None:
        """Create a new never-saved document."""
        self.app_call(lambda app: app.Documents.Add())

    def close_all(self, *, keep_unsaved: bool = False) -> None:
        """Close every open document without saving (optionally sparing unsaved ones)."""

        def work(app: Any) -> None:
            for i in range(app.Documents.Count, 0, -1):
                document = app.Documents.Item(i)
                if keep_unsaved and not str(document.Path):
                    continue
                document.Close(0)

        self.app_call(work)

    def activate(self, path: Path) -> None:
        """Bring the document at ``path`` to the front."""
        self.worker.call(lambda backend: backend.activate(str(path)))

    def select(self, path: Path, start: int, end: int) -> None:
        """Select a character range in the open document at ``path``."""

        def work(app: Any) -> None:
            for i in range(1, app.Documents.Count + 1):
                document = app.Documents.Item(i)
                if str(document.FullName).casefold() == str(path).casefold():
                    document.Activate()
                    document.Range(start, end).Select()

        self.app_call(work)


@pytest.fixture
def com_thread() -> Iterator[None]:
    """Initialise COM on the test thread (needed to create the sample documents)."""
    if sys.platform != "win32":
        pytest.skip("COM needs Windows")
    import pythoncom

    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


@pytest.fixture
def docs(com_thread: None, tmp_path: Path) -> dict[str, Path]:
    """Create the sample documents in a temp folder and map short names to paths."""
    paths = load_make_docs().make_docs(tmp_path / "docs", paragraphs=300)
    alpha, beta, gamma, space = (p.resolve() for p in paths)
    return {"alpha": alpha, "beta": beta, "gamma": gamma, "space": space}


@pytest.fixture
def harness(isolated_home: Path, docs: dict[str, Path]) -> Iterator[WordHarness]:
    """Yield a harness over one private invisible Word, quit at teardown.

    Depends on ``docs`` so the helper Word that writes the documents has quit
    before this Word starts (it must never quit the wrong process).
    """
    worker = ComWorker(lambda: ComWordBackend(isolated=True), call_timeout=_CALL_TIMEOUT)
    worker.start()
    service = _KeepAliveService(SessionStore(isolated_home / "sessions"), worker, Settings())
    pid = None
    try:
        worker.call(lambda b: b.connect(start_if_needed=True))
        pid = worker.call(lambda b: _pid(b))
        yield WordHarness(service, worker)
    finally:
        service.really_close()
        load_make_docs().wait_for_exit(pid)


@pytest.fixture
def second_word(harness: WordHarness) -> Iterator[ComWorker]:
    """Yield a worker over another private Word, used to lock files."""
    worker = ComWorker(lambda: ComWordBackend(isolated=True), call_timeout=_CALL_TIMEOUT)
    worker.start()
    pid = None
    try:
        worker.call(lambda b: b.connect(start_if_needed=True))
        pid = worker.call(lambda b: _pid(b))
        yield worker
    finally:
        worker.stop()
        load_make_docs().wait_for_exit(pid)


def last_json(capsys: pytest.CaptureFixture[str]) -> Any:
    """Parse the last line printed on stdout since the previous read as JSON."""
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])
