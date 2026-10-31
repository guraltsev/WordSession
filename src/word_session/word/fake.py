"""A scriptable in-memory ``WordBackend`` for tests and the demo server.

Construct ``FakeWordBackend`` with the documents Word should appear to have
open, then drive it through the ``WordBackend`` interface. Public attributes
(``busy_calls``, ``fail_paths``, ``hang``, ``calls``, ``active_index``) script
failures and record behavior. All state is guarded by a lock so worker threads
can share one instance.
"""

import threading
from dataclasses import dataclass, field

from word_session.model import DocumentState, Position, classify_location
from word_session.word.backend import (
    DocumentLocked,
    DocumentMissing,
    OpenOutcome,
    WordBusy,
    WordError,
    WordInfo,
    WordUnavailable,
)


@dataclass
class FakeDocument:
    """Describe one document open in the fake Word."""

    path: str
    length: int = 10_000
    position: Position = field(default_factory=Position)
    read_only: bool = False
    saved: bool = True


class FakeWordBackend:
    """Implement ``WordBackend`` entirely in memory.

    Parameters
    ----------
    running : bool
        Whether Word starts out running.
    installed : bool
        When False, ``connect(start_if_needed=True)`` raises ``WordUnavailable``.
    documents : list[FakeDocument] | None
        Documents open at start; the last one is active.
    existing_paths : set[str] | None
        Paths that exist on disk; ``None`` means every path exists.
    locked_paths : set[str] | None
        Paths locked by another process.
    version : str
        Version string reported by ``info``.

    Attributes
    ----------
    busy_calls : int
        The next this-many calls raise ``WordBusy``.
    fail_paths : dict[str, Exception]
        ``open_document`` for such a path raises the mapped exception.
    hang : threading.Event | None
        When not None, every call first waits for the event to be set.
    calls : list[str]
        Names of the methods called, in call order.
    active_index : int | None
        Index of the active document, or None when none is open.
    """

    def __init__(
        self,
        *,
        running: bool = True,
        installed: bool = True,
        documents: list[FakeDocument] | None = None,
        existing_paths: set[str] | None = None,
        locked_paths: set[str] | None = None,
        version: str = "16.0",
    ) -> None:
        self.running = running
        self.installed = installed
        self.documents: list[FakeDocument] = list(documents or [])
        self.existing_paths = existing_paths
        self.locked_paths = locked_paths or set()
        self.version = version
        self.busy_calls = 0
        self.fail_paths: dict[str, Exception] = {}
        self.hang: threading.Event | None = None
        self.calls: list[str] = []
        self.active_index: int | None = len(self.documents) - 1 if self.documents else None
        self._connected = False
        self._lock = threading.Lock()

    # -- WordBackend interface ----------------------------------------------

    def is_running(self) -> bool:
        """Return whether the fake Word is running."""
        self._enter("is_running", scripted=False)
        with self._lock:
            return self.running

    def connect(self, *, start_if_needed: bool) -> None:
        """Attach to the fake Word, starting it when allowed and installed."""
        self._enter("connect")
        with self._lock:
            # Start Word on request; an uninstalled Word can never start.
            if not self.running:
                if not start_if_needed or not self.installed:
                    raise WordUnavailable("Word is not running")
                self.running = True
            self._connected = True

    def info(self) -> WordInfo:
        """Return application facts; only ``running`` when not connected."""
        self._enter("info")
        with self._lock:
            if not self._connected:
                return WordInfo(running=self.running)
            return WordInfo(
                running=self.running,
                version=self.version,
                visible=True,
                document_count=len(self.documents),
            )

    def list_documents(self) -> list[DocumentState]:
        """Return the open documents in order, marking the active one."""
        self._enter("list_documents")
        with self._lock:
            self._require_connected()
            return [
                DocumentState(
                    path=d.path,
                    location=classify_location(d.path),
                    position=d.position.model_copy(),
                    active=(i == self.active_index),
                    read_only=d.read_only,
                    had_unsaved_changes=not d.saved,
                )
                for i, d in enumerate(self.documents)
            ]

    def open_document(self, doc: DocumentState, *, read_only: bool = False) -> OpenOutcome:
        """Open a document, making it active, unless it is already open."""
        self._enter("open_document")
        with self._lock:
            self._require_connected()
            # A path that is already open is never reopened.
            if self._find(doc.path) is not None:
                return "already_open"
            # Scripted failures win over the generic missing/locked checks.
            failure = self._lookup(self.fail_paths, doc.path)
            if failure is not None:
                raise failure
            if self.existing_paths is not None and not self._contains(
                self.existing_paths, doc.path
            ):
                raise DocumentMissing(f"File not found: {doc.path}")
            if self._contains(self.locked_paths, doc.path):
                raise DocumentLocked(f"File is locked: {doc.path}")
            # Append the new document and bring it to the front.
            self.documents.append(FakeDocument(path=doc.path, read_only=read_only or doc.read_only))
            self.active_index = len(self.documents) - 1
            return "opened"

    def restore_position(self, doc: DocumentState) -> None:
        """Store the saved position, clamped to the document length."""
        self._enter("restore_position")
        with self._lock:
            self._require_connected()
            index = self._find(doc.path)
            if index is None:
                raise WordError(f"Document is not open: {doc.path}")
            target = self.documents[index]
            pos = doc.position
            # Character offsets take priority; clamp them into the document.
            if pos.start is not None:
                start = min(max(pos.start, 0), target.length)
                end = start if pos.end is None else min(max(pos.end, start), target.length)
                target.position = Position(start=start, end=end)
            elif pos.page is not None:
                target.position = Position(page=pos.page, line=pos.line)

    def activate(self, path: str) -> None:
        """Make the named open document the active one."""
        self._enter("activate")
        with self._lock:
            self._require_connected()
            index = self._find(path)
            if index is None:
                raise WordError(f"Document is not open: {path}")
            self.active_index = index

    def close_document(self, path: str) -> None:
        """Close the named open document, keeping the active index valid."""
        self._enter("close_document")
        with self._lock:
            self._require_connected()
            index = self._find(path)
            if index is None:
                raise WordError(f"Document is not open: {path}")
            del self.documents[index]
            if self.active_index > index or self.active_index >= len(self.documents):
                self.active_index = max(self.active_index - 1, 0)

    def disconnect(self) -> None:
        """Drop the connection; the fake Word keeps running."""
        self._enter("disconnect", scripted=False)
        with self._lock:
            self._connected = False

    # -- Internals ------------------------------------------------------------

    def _enter(self, name: str, *, scripted: bool = True) -> None:
        """Record a call, wait on ``hang`` and consume one scripted busy failure."""
        with self._lock:
            self.calls.append(name)
        hang = self.hang
        if hang is not None:
            hang.wait()
        # Busy failures apply to calls that could really be rejected by Word.
        if scripted:
            with self._lock:
                if self.busy_calls > 0:
                    self.busy_calls -= 1
                    raise WordBusy("Word is busy")

    def _require_connected(self) -> None:
        """Raise ``WordError`` unless ``connect`` succeeded (lock must be held)."""
        if not self._connected:
            raise WordError("not connected")

    def _find(self, path: str) -> int | None:
        """Return the index of the open document with this path, ignoring case."""
        key = path.casefold()
        for i, d in enumerate(self.documents):
            if d.path.casefold() == key:
                return i
        return None

    @staticmethod
    def _contains(paths: set[str], path: str) -> bool:
        """Return whether ``path`` is in ``paths``, ignoring case."""
        return path.casefold() in {p.casefold() for p in paths}

    @staticmethod
    def _lookup(mapping: dict[str, Exception], path: str) -> Exception | None:
        """Return the scripted exception for ``path``, ignoring case."""
        key = path.casefold()
        for p, exc in mapping.items():
            if p.casefold() == key:
                return exc
        return None
