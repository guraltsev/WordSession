"""Fixtures that run the backend contract against the fake and the COM backend."""

from collections.abc import Callable

import pytest

from word_session.word.backend import WordBackend
from word_session.word.fake import FakeDocument, FakeWordBackend

DOC_A = "C:\\docs\\A.docx"
DOC_B = "C:\\docs\\B.docx"

BackendFactory = Callable[..., WordBackend]


@pytest.fixture(params=["fake", pytest.param("com", marks=pytest.mark.word)])
def backend_factory(request: pytest.FixtureRequest) -> BackendFactory:
    """Return a factory building an unconnected backend of the parametrised kind.

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

        return make_fake

    # TODO(job 09): build ComWordBackend instances with an isolated Word.
    pytest.skip("COM backend not implemented yet")


@pytest.fixture
def connected_backend(backend_factory: BackendFactory) -> WordBackend:
    """Return a connected backend with documents A and B open and B active."""
    backend = backend_factory(running=True, documents=[DOC_A, DOC_B])
    backend.connect(start_if_needed=False)
    return backend
