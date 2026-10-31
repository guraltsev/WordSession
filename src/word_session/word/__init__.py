"""Word backend interface, errors and the in-memory fake."""

from word_session.word.backend import (
    DocumentLocked,
    DocumentMissing,
    OpenOutcome,
    WordBackend,
    WordBusy,
    WordError,
    WordInfo,
    WordNotResponding,
    WordUnavailable,
)
from word_session.word.fake import FakeDocument, FakeWordBackend

__all__ = [
    "DocumentLocked",
    "DocumentMissing",
    "FakeDocument",
    "FakeWordBackend",
    "OpenOutcome",
    "WordBackend",
    "WordBusy",
    "WordError",
    "WordInfo",
    "WordNotResponding",
    "WordUnavailable",
]
