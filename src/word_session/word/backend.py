"""The single interface through which Word Session talks to Microsoft Word.

Implement ``WordBackend`` to provide a Word connection; the COM backend and
``FakeWordBackend`` both satisfy it. Every failure surfaces as a ``WordError``
subclass so callers never see COM exceptions.
"""

from typing import Literal, Protocol

from pydantic import BaseModel

from word_session.model import DocumentState


class WordError(Exception):
    """Report any failure while talking to Word."""


class WordUnavailable(WordError):
    """Report that Word is not running and may not start, or is not installed."""


class WordNotResponding(WordError):
    """Report that a call exceeded its timeout (raised by the worker)."""


class WordBusy(WordError):
    """Report that Word rejected the call and the caller should retry later."""


class DocumentMissing(WordError):
    """Report that a document file does not exist."""


class DocumentLocked(WordError):
    """Report that a document file is locked by another process."""


OpenOutcome = Literal["opened", "already_open"]


class WordInfo(BaseModel):
    """Describe the state of the Word application."""

    running: bool
    version: str = ""
    visible: bool = False
    document_count: int = 0


class WordBackend(Protocol):
    """Define the operations the app needs from Word.

    Every method except ``is_running`` and ``disconnect`` requires a prior
    ``connect`` and otherwise raises ``WordError("not connected")``.
    """

    def is_running(self) -> bool:
        """Return whether Word is running without starting it.

        Returns
        -------
        bool
            True when a Word instance is running. This check is cheap and
            never raises for "not running".
        """
        ...

    def connect(self, *, start_if_needed: bool) -> None:
        """Attach to Word, optionally starting it.

        Parameters
        ----------
        start_if_needed : bool
            When True, start Word (visible) if it is not running.

        Raises
        ------
        WordUnavailable
            If Word is not running and ``start_if_needed`` is False, or Word
            cannot be started.

        Notes
        -----
        Calling ``connect`` again while connected is a no-op.
        """
        ...

    def info(self) -> WordInfo:
        """Return facts about the Word application.

        Returns
        -------
        WordInfo
            Real values when connected. When not connected only ``running``
            is meaningful and the other fields keep their defaults.
        """
        ...

    def list_documents(self) -> list[DocumentState]:
        """List the open documents without changing which one is active.

        Returns
        -------
        list[DocumentState]
            One entry per open document in Word's collection order, with
            exactly one ``active=True`` entry when any document is open.

        Raises
        ------
        WordError
            If not connected.
        """
        ...

    def open_document(self, doc: DocumentState, *, read_only: bool = False) -> OpenOutcome:
        """Open a document unless it is already open.

        Parameters
        ----------
        doc : DocumentState
            The document to open; ``doc.path`` is compared case-insensitively
            with the open documents.
        read_only : bool
            Open the document read-only.

        Returns
        -------
        OpenOutcome
            ``"already_open"`` (no reopen) or ``"opened"``.

        Raises
        ------
        DocumentMissing
            If the file does not exist.
        DocumentLocked
            If another process has locked the file.
        WordError
            For any other failure, carrying Word's message.

        Notes
        -----
        Never shows a modal dialog.
        """
        ...

    def restore_position(self, doc: DocumentState) -> None:
        """Move the cursor of an open document to the saved position.

        Parameters
        ----------
        doc : DocumentState
            Provides the path and the position. ``position.start``/``end``
            are clamped to the document length when present; otherwise
            page/line is used; otherwise nothing happens.

        Raises
        ------
        WordError
            If the document is not open. Out-of-range positions do not raise.
        """
        ...

    def activate(self, path: str) -> None:
        """Bring an open document to the front.

        Parameters
        ----------
        path : str
            Path of an open document.

        Raises
        ------
        WordError
            If the document is not open.
        """
        ...

    def close_document(self, path: str) -> None:
        """Close an open document without saving it.

        Parameters
        ----------
        path : str
            Path of an open document.

        Raises
        ------
        WordError
            If the document is not open or Word refuses to close it.
        """
        ...

    def disconnect(self) -> None:
        """Drop references to Word; never raises and leaves Word running."""
        ...
