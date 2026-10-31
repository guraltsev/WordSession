"""Integration tests for ``ComWordBackend`` against private invisible Word processes."""

from pathlib import Path
from typing import Any

import pytest

from word_session.model import DocumentState, Position
from word_session.word.backend import (
    DocumentLocked,
    DocumentMissing,
    WordError,
    WordUnavailable,
)
from word_session.word.com import ComWordBackend

from .conftest import DocxFactory

pytestmark = pytest.mark.word


def _state(path: Path | str, **position: int) -> DocumentState:
    """Build a local document state with the given position fields."""
    return DocumentState(path=str(path), location="local", position=Position(**position))


def _app(word: ComWordBackend) -> Any:
    """Return the raw Word application behind a connected backend."""
    return word._app


def test_empty_instance_lists_nothing_and_reports_info(word: ComWordBackend) -> None:
    assert word.list_documents() == []
    info = word.info()
    assert info.running is True
    assert info.version != ""
    assert info.visible is False
    assert info.document_count == 0


def test_two_documents_listed_in_order_one_active(
    word: ComWordBackend, docx_factory: DocxFactory
) -> None:
    a, b = docx_factory("a.docx"), docx_factory("b.docx")
    word.open_document(_state(a))
    word.open_document(_state(b))
    word.activate(str(a))
    before = _app(word).ActiveDocument.FullName
    docs = word.list_documents()
    assert [d.path.casefold() for d in docs] == [str(a).casefold(), str(b).casefold()]
    assert [d.active for d in docs] == [True, False]
    assert _app(word).ActiveDocument.FullName == before


def test_capture_close_reopen_restore_selection(
    word: ComWordBackend, docx_factory: DocxFactory
) -> None:
    a = docx_factory("a.docx")
    word.open_document(_state(a))
    _app(word).ActiveDocument.Range(1234, 1240).Select()
    captured = word.list_documents()[0]
    assert (captured.position.start, captured.position.end) == (1234, 1240)
    assert captured.position.page is not None

    _app(word).ActiveDocument.Close(0)
    assert word.list_documents() == []
    word.open_document(captured)
    word.restore_position(captured)
    assert _app(word).Selection.Start == 1234


def test_restore_clamps_beyond_document_end(
    word: ComWordBackend, docx_factory: DocxFactory
) -> None:
    a = docx_factory("a.docx", paragraphs=5)
    word.open_document(_state(a))
    word.restore_position(_state(a, start=10**7, end=10**7 + 3))
    length = _app(word).ActiveDocument.Content.End
    assert length - 1 <= _app(word).Selection.Start <= length


def test_page_line_fallback(word: ComWordBackend, docx_factory: DocxFactory) -> None:
    a = docx_factory("a.docx")
    word.open_document(_state(a))
    word.restore_position(_state(a, page=3, line=5))
    assert word.list_documents()[0].position.page == 3


def test_missing_file_raises(word: ComWordBackend, tmp_path: Path) -> None:
    with pytest.raises(DocumentMissing):
        word.open_document(_state(tmp_path / "nope.docx"))


def test_locked_file_raises_unless_read_only(
    word: ComWordBackend, docx_factory: DocxFactory
) -> None:
    a = docx_factory("a.docx")
    other = ComWordBackend(isolated=True)
    other.connect(start_if_needed=True)
    try:
        other.open_document(_state(a))
        with pytest.raises(DocumentLocked):
            word.open_document(_state(a))
        assert word.open_document(_state(a), read_only=True) == "opened"
    finally:
        other.disconnect()


def test_already_open_ignores_case(word: ComWordBackend, docx_factory: DocxFactory) -> None:
    a = docx_factory("a.docx")
    assert word.open_document(_state(a)) == "opened"
    assert word.open_document(_state(str(a).upper())) == "already_open"
    assert len(word.list_documents()) == 1


def test_unsaved_document_has_unsaved_location(word: ComWordBackend) -> None:
    _app(word).Documents.Add()
    docs = word.list_documents()
    assert len(docs) == 1
    assert docs[0].location == "unsaved"


def test_unknown_document_errors(word: ComWordBackend, tmp_path: Path) -> None:
    with pytest.raises(WordError):
        word.activate(str(tmp_path / "x.docx"))
    with pytest.raises(WordError):
        word.restore_position(_state(tmp_path / "x.docx", start=1))


def test_connect_after_process_quit(word: ComWordBackend) -> None:
    _app(word).Quit(0)
    with pytest.raises(WordUnavailable):
        word.connect(start_if_needed=False)
    word.connect(start_if_needed=True)
    assert word.info().running is True
