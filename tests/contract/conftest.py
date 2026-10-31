"""Fixtures that run the backend contract against the fake and the COM backend."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from tests.integration.conftest import (  # noqa: F401  (fixtures re-exported for the COM branch)
    com_initialised,
    docx_factory,
)
from word_session.model import DocumentState
from word_session.word.backend import OpenOutcome, WordBackend, WordError, WordInfo
from word_session.word.fake import FakeDocument, FakeWordBackend

DOC_A = "C:\\docs\\A.docx"
DOC_B = "C:\\docs\\B.docx"

BackendFactory = Callable[..., WordBackend]


@pytest.fixture(params=["fake", pytest.param("com", marks=pytest.mark.word)])
def backend_factory(request: pytest.FixtureRequest) -> Iterator[BackendFactory]:
    """Yield a factory building an unconnected backend of the parametrised kind.

    The factory accepts ``running`` and ``documents`` (a list of paths opened
    in order, the last one active).
    """
    if request.param == "fake":

        def make_fake(*, running: bool = True, documents: list[str] | None = None) -> WordBackend:
            docs = [FakeDocument(path=p) for p in documents or []]
            # Only the open documents exist on disk, so any other path is missing.
            return FakeWordBackend(
                running=running, documents=docs, existing_paths=set(documents or [])
            )

        yield make_fake
        return

    # Build isolated-Word backends; every one is quit at teardown.
    from word_session.word.com import ComWordBackend

    make_docx = request.getfixturevalue("docx_factory")
    created: list[ComWordBackend] = []

    def make_com(*, running: bool = True, documents: list[str] | None = None) -> WordBackend:
        real = ComWordBackend(isolated=True)
        created.append(real)
        paths: dict[str, str] = {}
        # Start Word eagerly and open real files standing in for the virtual paths.
        if running:
            real.connect(start_if_needed=True)
            for virtual in documents or []:
                file = make_docx(virtual.rsplit("\\", 1)[-1])
                paths[virtual.casefold()] = str(file)
                real.open_document(DocumentState(path=str(file), location="local"))
        return _IsolatedContractBackend(real, paths, {v.casefold(): v for v in documents or []})

    try:
        yield make_com
    finally:
        for real in created:
            real.disconnect()


@pytest.fixture
def connected_backend(backend_factory: BackendFactory) -> WordBackend:
    """Return a connected backend with documents A and B open and B active."""
    backend = backend_factory(running=True, documents=[DOC_A, DOC_B])
    backend.connect(start_if_needed=False)
    return backend


class _IsolatedContractBackend:
    """Adapt an isolated ``ComWordBackend`` to the contract's expectations.

    The wrapper gates calls on an explicit connected flag (the real backend is
    already running), maps the contract's virtual document paths to real
    ``.docx`` files and keeps Word running on ``disconnect``; the fixture quits
    Word at teardown.
    """

    def __init__(
        self, real: Any, real_paths: dict[str, str], virtual_names: dict[str, str]
    ) -> None:
        self._real = real
        self._real_paths = real_paths  # virtual (casefolded) -> real path
        self._virtual_names = virtual_names  # virtual (casefolded) -> virtual
        self._connected = False

    def _to_real(self, path: str) -> str:
        return self._real_paths.get(path.casefold(), path)

    def _to_virtual(self, path: str) -> str:
        for key, real in self._real_paths.items():
            if real.casefold() == path.casefold():
                return self._virtual_names[key]
        return path

    def _need(self) -> None:
        if not self._connected:
            raise WordError("not connected")

    def is_running(self) -> bool:
        return self._real.is_running()

    def connect(self, *, start_if_needed: bool) -> None:
        self._real.connect(start_if_needed=start_if_needed)
        self._connected = True

    def info(self) -> WordInfo:
        if not self._connected:
            return WordInfo(running=self._real.is_running())
        return self._real.info()

    def list_documents(self) -> list[DocumentState]:
        self._need()
        return [
            d.model_copy(update={"path": self._to_virtual(d.path)})
            for d in self._real.list_documents()
        ]

    def open_document(self, doc: DocumentState, *, read_only: bool = False) -> OpenOutcome:
        self._need()
        mapped = doc.model_copy(update={"path": self._to_real(doc.path)})
        return self._real.open_document(mapped, read_only=read_only)

    def restore_position(self, doc: DocumentState) -> None:
        self._need()
        self._real.restore_position(doc.model_copy(update={"path": self._to_real(doc.path)}))

    def activate(self, path: str) -> None:
        self._need()
        self._real.activate(self._to_real(path))

    def disconnect(self) -> None:
        self._connected = False
