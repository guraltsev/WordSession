"""Contract tests every ``WordBackend`` implementation must satisfy."""

import pytest

from word_session.model import DocumentState, Position
from word_session.word.backend import DocumentMissing, WordBackend, WordError, WordUnavailable

from .conftest import DOC_A, DOC_B, BackendFactory


def _state(path: str, **position: int) -> DocumentState:
    """Build a document state with the given position fields."""
    return DocumentState(path=path, location="local", position=Position(**position))


def test_is_running_does_not_start_word(backend_factory: BackendFactory) -> None:
    backend = backend_factory(running=False)
    assert backend.is_running() is False
    assert backend.is_running() is False


def test_connect_without_start_raises_when_not_running(backend_factory: BackendFactory) -> None:
    backend = backend_factory(running=False)
    with pytest.raises(WordUnavailable):
        backend.connect(start_if_needed=False)


def test_connect_with_start_is_idempotent(backend_factory: BackendFactory) -> None:
    backend = backend_factory(running=False)
    backend.connect(start_if_needed=True)
    backend.connect(start_if_needed=True)
    assert backend.is_running() is True


@pytest.mark.parametrize("method", ["list", "open", "restore", "activate"])
def test_methods_require_connect(backend_factory: BackendFactory, method: str) -> None:
    backend = backend_factory(running=True, documents=[DOC_A])
    calls = {
        "list": lambda: backend.list_documents(),
        "open": lambda: backend.open_document(_state(DOC_B)),
        "restore": lambda: backend.restore_position(_state(DOC_A, start=1)),
        "activate": lambda: backend.activate(DOC_A),
    }
    with pytest.raises(WordError, match="not connected"):
        calls[method]()


def test_info_when_not_connected_reports_only_running(backend_factory: BackendFactory) -> None:
    info = backend_factory(running=True, documents=[DOC_A]).info()
    assert info.running is True
    assert info.version == ""
    assert info.document_count == 0


def test_info_when_connected(connected_backend: WordBackend) -> None:
    info = connected_backend.info()
    assert info.running is True
    assert info.document_count == 2
    assert info.version != ""


def test_list_order_single_active_and_unchanged(connected_backend: WordBackend) -> None:
    first = connected_backend.list_documents()
    second = connected_backend.list_documents()
    assert [d.path for d in first] == [DOC_A, DOC_B]
    assert [d.active for d in first] == [False, True]
    assert [d.active for d in second] == [False, True]


def test_open_already_open_is_case_insensitive(connected_backend: WordBackend) -> None:
    assert connected_backend.open_document(_state(DOC_A.lower())) == "already_open"
    assert len(connected_backend.list_documents()) == 2


def test_open_missing_file_raises(backend_factory: BackendFactory) -> None:
    backend = backend_factory(running=True)
    backend.connect(start_if_needed=False)
    with pytest.raises(DocumentMissing):
        backend.open_document(_state("C:\\no\\such\\file.docx"))


def test_restore_position_clamps_to_length(connected_backend: WordBackend) -> None:
    # Offsets far beyond any document must clamp instead of raising.
    connected_backend.restore_position(_state(DOC_A, start=10**9, end=10**9 + 5))
    docs = connected_backend.list_documents()
    assert [d.active for d in docs] == [False, True]
    pos = docs[0].position
    assert pos.start is not None and pos.end is not None
    assert pos.start <= pos.end < 10**9


def test_restore_position_requires_open_document(connected_backend: WordBackend) -> None:
    with pytest.raises(WordError):
        connected_backend.restore_position(_state("C:\\docs\\other.docx", start=1))


def test_activate_brings_document_to_front(connected_backend: WordBackend) -> None:
    connected_backend.activate(DOC_A)
    assert [d.active for d in connected_backend.list_documents()] == [True, False]


def test_activate_unknown_document_raises(connected_backend: WordBackend) -> None:
    with pytest.raises(WordError):
        connected_backend.activate("C:\\docs\\other.docx")


def test_disconnect_is_idempotent_and_leaves_word_running(
    connected_backend: WordBackend,
) -> None:
    connected_backend.disconnect()
    connected_backend.disconnect()
    assert connected_backend.is_running() is True
    with pytest.raises(WordError, match="not connected"):
        connected_backend.list_documents()
