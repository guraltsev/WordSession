"""Attach-path tests against the Word instance the user left running."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from word_session.model import DocumentState, Position
from word_session.word.backend import WordUnavailable
from word_session.word.com import ComWordBackend

from .conftest import DocxFactory

pytestmark = pytest.mark.shared_word


def _state(path: Path | str, **position: int) -> DocumentState:
    """Build a local document state with the given position fields."""
    return DocumentState(path=str(path), location="local", position=Position(**position))


def _paths(app: Any) -> list[str]:
    """Return the full names of all open documents."""
    return [str(app.Documents.Item(i).FullName) for i in range(1, app.Documents.Count + 1)]


@pytest.fixture
def shared_word(com_initialised: None, tmp_path: Path) -> Iterator[ComWordBackend]:
    """Attach to the user's Word and clean up only documents under ``tmp_path``."""
    backend = ComWordBackend()
    try:
        backend.connect(start_if_needed=False)
    except WordUnavailable:
        pytest.skip("user's Word not reachable over COM (not in the ROT yet)")
    app = backend._app
    active = str(app.ActiveDocument.FullName) if app.Documents.Count else None
    before = _paths(app)
    try:
        yield backend
    finally:
        # Close only the documents this test created, discarding changes.
        root = str(tmp_path).casefold()
        for i in range(app.Documents.Count, 0, -1):
            document = app.Documents.Item(i)
            if str(document.FullName).casefold().startswith(root):
                document.Close(0)
        # Put the user's previously active document back in front.
        if active is not None:
            for i in range(1, app.Documents.Count + 1):
                if str(app.Documents.Item(i).FullName) == active:
                    app.Documents.Item(i).Activate()
        after = _paths(app)
        backend.disconnect()
        assert after == before


def test_attach_info_and_listing(shared_word: ComWordBackend, docx_factory: DocxFactory) -> None:
    app = shared_word._app
    assert shared_word.is_running() is True
    assert shared_word.info().running is True
    previous = _paths(app)

    a, b = docx_factory("a.docx"), docx_factory("b.docx")
    shared_word.open_document(_state(a))
    shared_word.open_document(_state(b))
    active_before = str(app.ActiveDocument.FullName)

    docs = shared_word.list_documents()
    listed = [d.path.casefold() for d in docs]
    for path in [*previous, str(a), str(b)]:
        assert path.casefold() in listed
    assert sum(d.active for d in docs) == 1
    assert str(app.ActiveDocument.FullName) == active_before


def test_restore_and_already_open(shared_word: ComWordBackend, docx_factory: DocxFactory) -> None:
    a = docx_factory("a.docx")
    assert shared_word.open_document(_state(a)) == "opened"
    shared_word.restore_position(_state(a, start=300, end=310))
    assert shared_word._app.Selection.Start == 300
    assert shared_word.open_document(_state(a)) == "already_open"
