"""Real Microsoft Word backend built on pywin32 late-bound COM.

Construct ``ComWordBackend()`` to drive the user's running Word, or
``ComWordBackend(isolated=True)`` in tests to drive a private invisible Word
process. Every COM failure surfaces as a ``WordError`` subclass. The module
imports on every platform; constructing the backend without pywin32 raises
``WordUnavailable``.
"""

import contextlib
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from word_session.model import DocumentState, Position, WindowState, classify_location
from word_session.word import constants as wd
from word_session.word.backend import (
    DocumentLocked,
    DocumentMissing,
    OpenOutcome,
    WordBusy,
    WordError,
    WordInfo,
    WordUnavailable,
)

_log = logging.getLogger(__name__)


class ComWordBackend:
    """Implement ``WordBackend`` on top of real Word through pywin32.

    Parameters
    ----------
    isolated : bool
        False (normal use) attaches to the user's Word. True is for tests
        only: ``connect`` always creates a new invisible Word process with
        ``DispatchEx`` and never attaches to the user's Word, and
        ``disconnect`` quits that process without saving.

    Raises
    ------
    WordUnavailable
        If pywin32 is not installed.

    Notes
    -----
    All calls are synchronous and assume the calling thread has COM
    initialised.
    """

    def __init__(self, *, isolated: bool = False) -> None:
        try:
            import pythoncom  # noqa: F401
            import pywintypes  # noqa: F401
            import win32com.client  # noqa: F401
        except ImportError as exc:
            raise WordUnavailable("pywin32 is not installed") from exc
        self._isolated = isolated
        self._app: Any = None

    # -- WordBackend interface ----------------------------------------------

    def is_running(self) -> bool:
        """Return whether a Word instance is reachable, without starting one."""
        # An isolated backend only knows the process it started itself.
        if self._isolated:
            return self._app is not None and self._probe(self._app)

        # Otherwise ask the Running Object Table for a registered Word.
        import pythoncom
        import pywintypes

        try:
            pythoncom.GetActiveObject(pywintypes.IID("Word.Application"))
        except pywintypes.com_error as exc:
            _log.debug("Word not reachable: hresult=%s", getattr(exc, "hresult", None))
            return False
        return True

    def connect(self, *, start_if_needed: bool) -> None:
        """Attach to (or start) Word; a no-op while the connection is alive."""
        # Keep a live connection; drop a dead one and reconnect below.
        if self._app is not None:
            if self._probe(self._app):
                return
            _log.debug("Word connection lost; reconnecting")
            self._app = None

        # Isolated mode never attaches: it starts a private process or fails.
        if self._isolated:
            if not start_if_needed:
                raise WordUnavailable("Word is not running")
            self._app = self._start_isolated()
            return

        # Prefer attaching to the running Word; start one only when allowed.
        app = self._attach()
        if app is None:
            if not start_if_needed:
                raise WordUnavailable("Word is not running")
            app = self._start_visible()
        self._app = app

    def info(self) -> WordInfo:
        """Return facts about Word; only ``running`` when not connected."""
        # Without a connection only the cheap running check is meaningful.
        if self._app is None:
            return WordInfo(running=self.is_running())
        with _translated():
            app = self._app
            return WordInfo(
                running=True,
                version=str(app.Version),
                visible=bool(app.Visible),
                document_count=int(app.Documents.Count),
            )

    def list_documents(self) -> list[DocumentState]:
        """List open documents, then protected-view ones, without activating any."""
        app = self._require_app()

        # Remember which document is active so each entry can be flagged.
        active_name: str | None = None
        with _translated():
            count = int(app.Documents.Count)
        if count:
            try:
                with _translated():
                    active_name = str(app.ActiveDocument.FullName)
            except WordBusy:
                raise
            except WordError as exc:
                _log.debug("Could not read the active document: %s", exc)

        # Read every document; one failing document must not abort the list.
        # Word indexes the newest document first, so walk backwards to report
        # documents in the order they were opened (restoring then keeps it).
        result: list[DocumentState] = []
        for i in range(count, 0, -1):
            state = self._read_document(app, i, active_name)
            if state is not None:
                result.append(state)

        # Protected-view documents are read-only and have no position.
        with _translated():
            protected = int(app.ProtectedViewWindows.Count)
        for j in range(1, protected + 1):
            try:
                with _translated():
                    window = app.ProtectedViewWindows.Item(j)
                    path = str(Path(str(window.SourcePath)) / str(window.SourceName))
            except WordBusy:
                raise
            except WordError as exc:
                _log.debug("Could not read protected view window %d: %s", j, exc)
                continue
            result.append(
                DocumentState(path=path, location=classify_location(path), read_only=True)
            )
        return result

    def open_document(self, doc: DocumentState, *, read_only: bool = False) -> OpenOutcome:
        """Open a document unless it is already open, never showing a dialog."""
        app = self._require_app()
        with _translated():
            # A path that is already open is never reopened.
            if self._find_document(app, doc.path) is not None:
                return "already_open"

            # Unsaved documents have no file to open.
            location = classify_location(doc.path)
            if location == "unsaved":
                raise WordError("document was never saved")

            # Local and UNC files are checked up front for a clear error.
            read_only = read_only or doc.read_only
            if location in ("local", "unc"):
                path = Path(doc.path)
                if not path.exists():
                    raise DocumentMissing(f"File not found: {doc.path}")
                # Word holds files with deny-write; CPython opens with share
                # read/write, so this probe detects the lock without taking one.
                if not read_only:
                    try:
                        with path.open("r+b"):
                            pass
                    except PermissionError as exc:
                        raise DocumentLocked(f"File is locked: {doc.path}") from exc

            # Suppress alerts only for the duration of the open call.
            previous_alerts = app.DisplayAlerts
            app.DisplayAlerts = wd.wdAlertsNone
            try:
                # Positional arguments: late binding does not accept keywords.
                # (FileName, ConfirmConversions, ReadOnly, AddToRecentFiles);
                # Visible defaults to True.
                app.Documents.Open(doc.path, False, read_only, False)
            finally:
                app.DisplayAlerts = previous_alerts
        return "opened"

    def restore_position(self, doc: DocumentState) -> None:
        """Select the saved range (or page/line) in an open document."""
        app = self._require_app()
        with _translated():
            document = self._find_document(app, doc.path)
            if document is None:
                raise WordError(f"Document is not open: {doc.path}")
            pos = doc.position
            # Selecting needs the document active; remember who was in front
            # so a restore does not steal focus (activate() is the explicit way).
            previous = app.ActiveDocument if int(app.Documents.Count) else None

            # Character offsets take priority; clamp them into the document.
            if pos.start is not None:
                # Word rejects a range at Content.End (after the final paragraph mark).
                length = max(int(document.Content.End) - 1, 0)
                start = min(max(pos.start, 0), length)
                end = start if pos.end is None else min(max(pos.end, start), length)
                document.Activate()
                document.Range(start, end).Select()
                # Scrolling is cosmetic; a failure must not fail the restore.
                try:
                    document.Windows.Item(1).ScrollIntoView(document.Range(start, end))
                except Exception as exc:
                    _log.debug("ScrollIntoView failed: %s", exc)
                self._reactivate(previous, document)
                return

            # Fall back to page and line, as the legacy tool did.
            if pos.page is not None:
                document.Activate()
                selection = document.Windows.Item(1).Selection
                selection.GoTo(wd.wdGoToPage, wd.wdGoToAbsolute, pos.page)
                if pos.line is not None and pos.line > 1:
                    selection.GoTo(wd.wdGoToLine, wd.wdGoToRelative, pos.line - 1)
                self._reactivate(previous, document)

    def activate(self, path: str) -> None:
        """Bring the open document with this path to the front."""
        app = self._require_app()
        with _translated():
            document = self._find_document(app, path)
            if document is None:
                raise WordError(f"Document is not open: {path}")
            document.Activate()

    def disconnect(self) -> None:
        """Drop the Word reference (quitting a private isolated Word); never raises."""
        app, self._app = self._app, None
        # Only a Word process this backend started itself may be quit.
        if app is not None and self._isolated:
            try:
                app.Quit(wd.wdDoNotSaveChanges)
            except Exception as exc:
                _log.debug("Quit of isolated Word failed: %s", exc)

    @staticmethod
    def _reactivate(previous: Any, current: Any) -> None:
        """Bring ``previous`` back to the front after ``current`` was activated."""
        if previous is None:
            return
        try:
            if str(previous.FullName) != str(current.FullName):
                previous.Activate()
        except Exception as exc:
            _log.debug("Could not restore the active document: %s", exc)

    # -- Connection helpers ----------------------------------------------------

    def _require_app(self) -> Any:
        """Return the connected application or raise ``WordError``."""
        if self._app is None:
            raise WordError("not connected")
        return self._app

    @staticmethod
    def _probe(app: Any) -> bool:
        """Return whether the application still answers a trivial call."""
        try:
            _ = app.Version
        except Exception as exc:
            _log.debug("Word probe failed: %s", exc)
            return False
        return True

    @staticmethod
    def _attach() -> Any:
        """Return a late-bound running Word, or None when none is registered."""
        import pythoncom
        import pywintypes
        import win32com.client.dynamic

        try:
            unknown = pythoncom.GetActiveObject(pywintypes.IID("Word.Application"))
            dispatch = unknown.QueryInterface(pythoncom.IID_IDispatch)
        except pywintypes.com_error as exc:
            hresult = getattr(exc, "hresult", None)
            _log.debug("Attach failed: hresult=%s", hresult)
            if hresult == wd.MK_E_UNAVAILABLE:
                return None
            raise _translate_com_error(exc) from exc
        return win32com.client.dynamic.Dispatch(dispatch)

    @staticmethod
    def _start_visible() -> Any:
        """Start Word, make it visible and return it late-bound."""
        import pywintypes
        import win32com.client.dynamic

        try:
            app = win32com.client.dynamic.Dispatch("Word.Application")
            app.Visible = True
        except pywintypes.com_error as exc:
            raise WordUnavailable(
                f"Word could not be started: {_translate_com_error(exc)}"
            ) from exc
        return app

    @staticmethod
    def _start_isolated() -> Any:
        """Create a new invisible Word process (tests only) and return it late-bound."""
        import pywintypes
        import win32com.client
        import win32com.client.dynamic

        try:
            raw = win32com.client.DispatchEx("Word.Application")
            app = win32com.client.dynamic.Dispatch(raw._oleobj_)
            app.Visible = False
            app.DisplayAlerts = wd.wdAlertsNone
        except pywintypes.com_error as exc:
            raise WordUnavailable(
                f"Word could not be started: {_translate_com_error(exc)}"
            ) from exc
        return app

    # -- Document helpers ------------------------------------------------------

    @staticmethod
    def _find_document(app: Any, path: str) -> Any:
        """Return the open document whose FullName equals ``path`` ignoring case."""
        key = path.casefold()
        for i in range(1, int(app.Documents.Count) + 1):
            document = app.Documents.Item(i)
            if str(document.FullName).casefold() == key:
                return document
        return None

    @staticmethod
    def _read_document(app: Any, index: int, active_name: str | None) -> DocumentState | None:
        """Read one open document, keeping whatever could be read on failure."""
        # The path identifies the entry; without it there is nothing to list.
        try:
            with _translated():
                document = app.Documents.Item(index)
                path = str(document.FullName)
        except WordBusy:
            raise
        except WordError as exc:
            _log.warning("Could not read document %d: %s", index, exc)
            return None

        # Fill the remaining fields one by one so a late failure keeps the rest.
        position = Position()
        read_only = False
        unsaved = False
        window_state: WindowState | None = None
        try:
            with _translated():
                window = document.Windows.Item(1)
                selection = window.Selection
                position.start, position.end = int(selection.Start), int(selection.End)
                page = int(selection.Information(wd.wdActiveEndPageNumber))
                line = int(selection.Information(wd.wdFirstCharacterLineNumber))
                position.page = page if page > 0 else None
                position.line = line if line > 0 else None
                read_only = bool(document.ReadOnly)
                unsaved = not document.Saved
                names = {
                    wd.wdWindowStateNormal: "normal",
                    wd.wdWindowStateMaximize: "maximized",
                    wd.wdWindowStateMinimize: "minimized",
                }
                state = names.get(int(window.WindowState))
                window_state = WindowState(state=state) if state else None  # type: ignore[arg-type]
        except WordBusy:
            raise
        except WordError as exc:
            _log.warning("Partial read of document %s: %s", path, exc)

        return DocumentState(
            path=path,
            location=classify_location(path),
            position=position,
            active=path == active_name,
            read_only=read_only,
            had_unsaved_changes=unsaved,
            window=window_state,
        )


# -- Error translation ---------------------------------------------------------


@contextlib.contextmanager
def _translated() -> Iterator[None]:
    """Convert COM errors raised inside the block into ``WordError`` subclasses."""
    import pywintypes

    try:
        yield
    except pywintypes.com_error as exc:
        raise _translate_com_error(exc) from exc


def _translate_com_error(exc: Any) -> WordError:
    """Map a ``pywintypes.com_error`` to ``WordBusy`` or ``WordError``."""
    hresult = getattr(exc, "hresult", None)
    excepinfo = getattr(exc, "excepinfo", None)
    # Methods report the real code in the exception info's scode.
    scode = excepinfo[5] if excepinfo and len(excepinfo) > 5 else None
    _log.debug("COM error: hresult=%s scode=%s", hresult, scode)

    busy = (wd.RPC_E_CALL_REJECTED, wd.RPC_E_SERVERCALL_RETRYLATER)
    if hresult in busy or scode in busy:
        return WordBusy("Word is busy")
    description = excepinfo[2] if excepinfo and len(excepinfo) > 2 and excepinfo[2] else None
    return WordError(str(description or exc))
