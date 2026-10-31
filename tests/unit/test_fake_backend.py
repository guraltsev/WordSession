"""Tests for the scripting knobs of ``FakeWordBackend``."""

import threading

import pytest

from word_session.model import DocumentState, Position
from word_session.word.backend import (
    DocumentLocked,
    DocumentMissing,
    WordBusy,
    WordError,
    WordUnavailable,
)
from word_session.word.fake import FakeDocument, FakeWordBackend


def _state(path: str, position: Position | None = None) -> DocumentState:
    """Build a minimal local document state."""
    return DocumentState(path=path, location="local", position=position or Position())


def test_busy_calls_raise_then_recover() -> None:
    backend = FakeWordBackend()
    backend.connect(start_if_needed=False)
    backend.busy_calls = 2
    with pytest.raises(WordBusy):
        backend.list_documents()
    with pytest.raises(WordBusy):
        backend.info()
    assert backend.list_documents() == []
    assert backend.busy_calls == 0


def test_fail_paths_raise_scripted_exception() -> None:
    backend = FakeWordBackend()
    backend.connect(start_if_needed=False)
    backend.fail_paths["C:\\x.docx"] = WordError("boom")
    with pytest.raises(WordError, match="boom"):
        backend.open_document(_state("C:\\x.docx"))
    assert backend.list_documents() == []


def test_hang_blocks_until_released() -> None:
    backend = FakeWordBackend()
    gate = threading.Event()
    backend.hang = gate
    done = threading.Event()

    def run() -> None:
        backend.is_running()
        done.set()

    thread = threading.Thread(target=run)
    thread.start()
    assert not done.wait(0.05)
    gate.set()
    thread.join(timeout=5)
    assert done.is_set()


def test_calls_log_records_method_names_in_order() -> None:
    backend = FakeWordBackend()
    backend.is_running()
    backend.connect(start_if_needed=False)
    backend.list_documents()
    backend.disconnect()
    assert backend.calls == ["is_running", "connect", "list_documents", "disconnect"]


def test_not_installed_cannot_start() -> None:
    backend = FakeWordBackend(running=False, installed=False)
    with pytest.raises(WordUnavailable):
        backend.connect(start_if_needed=True)
    assert backend.is_running() is False


def test_open_appends_and_activates_with_missing_and_locked() -> None:
    backend = FakeWordBackend(
        documents=[FakeDocument(path="C:\\a.docx")],
        existing_paths={"C:\\a.docx", "C:\\b.docx", "C:\\l.docx"},
        locked_paths={"C:\\l.docx"},
    )
    backend.connect(start_if_needed=False)
    assert backend.open_document(_state("C:\\b.docx"), read_only=True) == "opened"
    assert backend.active_index == 1
    assert backend.documents[1].read_only is True
    with pytest.raises(DocumentMissing):
        backend.open_document(_state("C:\\gone.docx"))
    with pytest.raises(DocumentLocked):
        backend.open_document(_state("C:\\l.docx"))


def test_restore_position_stores_clamped_values_and_page_line() -> None:
    backend = FakeWordBackend(documents=[FakeDocument(path="C:\\a.docx", length=100)])
    backend.connect(start_if_needed=False)
    backend.restore_position(_state("C:\\a.docx", Position(start=500, end=900)))
    stored = backend.documents[0].position
    assert (stored.start, stored.end) == (100, 100)
    backend.restore_position(_state("C:\\a.docx", Position(page=3, line=4)))
    stored = backend.documents[0].position
    assert (stored.page, stored.line) == (3, 4)
