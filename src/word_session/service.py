"""Session use cases shared by the command line, tray and web API.

Build a ``SessionService`` (or call ``open_service()``) and use ``capture``,
``restore``, ``list_sessions``, ``update``, ``delete``, ``prune``,
``import_legacy`` and ``autosave_tick``. Every Word call goes through a
``ComWorker``; progress and changes are announced on the service's
``EventBus``. Restoring is reported per document and never aborts halfway.
"""

import fnmatch
import logging
import ntpath
import os
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from word_session import legacy
from word_session.config import Settings, app_paths, load_settings, resolve_sessions_dir
from word_session.events import EventBus
from word_session.legacy import ImportSummary
from word_session.model import (
    DocumentState,
    RestoreReport,
    RestoreResult,
    Session,
    SessionKind,
)
from word_session.store import SessionStore
from word_session.word.backend import (
    DocumentLocked,
    DocumentMissing,
    WordBackend,
    WordError,
    WordInfo,
)
from word_session.word.worker import ComWorker

_log = logging.getLogger(__name__)


class ServiceError(Exception):
    """Base class for errors raised by the session service."""


class RevisionConflict(ServiceError):
    """Report that a session changed since the caller last read it."""


class RestoreInProgress(ServiceError):
    """Report that another restore is already running."""


@dataclass
class CaptureResult:
    """Describe the outcome of a capture.

    Attributes
    ----------
    session : Session
        The captured session (not stored when ``path`` is None).
    warnings : list[str]
        Human-readable problems noticed while capturing.
    path : Path | None
        File the session was written to, or None when nothing was saved.
    """

    session: Session
    warnings: list[str]
    path: Path | None


@dataclass
class SessionDiff:
    """List the document paths that differ between two sessions.

    Attributes
    ----------
    added : list[str]
        Paths in the second session but not the first (case-insensitive).
    removed : list[str]
        Paths in the first session but not the second.
    """

    added: list[str]
    removed: list[str]


class SessionService:
    """Implement every session use case on top of a store and a Word worker.

    Parameters
    ----------
    store : SessionStore
        Where sessions are saved.
    worker : ComWorker
        Started worker that owns the Word backend.
    settings : Settings
        User settings consulted for defaults.
    events : EventBus | None
        Bus to publish on; a new one is created when omitted.
    clock : Callable[[], datetime] | None
        Source of timezone-aware "now"; defaults to the system clock.
    host : str | None
        Host name recorded in sessions; defaults to ``socket.gethostname()``.
    path_exists : Callable[[str], bool] | None
        Existence check for local paths; defaults to ``os.path.exists``.

    Attributes
    ----------
    events : EventBus
        Event bus the service publishes on.
    settings : Settings
        Settings in effect.
    store : SessionStore
        Underlying session store.
    restore_in_progress : bool
        True while a restore is running.
    """

    def __init__(
        self,
        store: SessionStore,
        worker: ComWorker,
        settings: Settings,
        *,
        events: EventBus | None = None,
        clock: Callable[[], datetime] | None = None,
        host: str | None = None,
        path_exists: Callable[[str], bool] | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.events = events if events is not None else EventBus()
        self._worker = worker
        self._clock = clock if clock is not None else lambda: datetime.now().astimezone()
        self._host = host if host is not None else socket.gethostname()
        self._path_exists = path_exists if path_exists is not None else os.path.exists
        self._restore_lock = threading.Lock()
        self._restoring = False

    @property
    def restore_in_progress(self) -> bool:
        """Return whether a restore is currently running."""
        return self._restoring

    # ---- Word facts ------------------------------------------------------

    def word_info(self) -> WordInfo:
        """Return facts about Word without connecting to or starting it."""
        return self._worker.call(lambda b: b.info())

    def current(self) -> list[DocumentState]:
        """List the documents open in a running Word.

        Raises
        ------
        WordUnavailable
            If Word is not running (it is never started here).
        """

        def work(backend: WordBackend) -> list[DocumentState]:
            backend.connect(start_if_needed=False)
            return backend.list_documents()

        return self._worker.call(work)

    # ---- capture ---------------------------------------------------------

    def capture(self, name: str | None = None, *, kind: SessionKind = "manual") -> CaptureResult:
        """Save the open Word documents as a new session.

        Parameters
        ----------
        name : str | None
            Session name; defaults to ``Session``/``Autosave`` plus the time.
        kind : SessionKind
            Kind recorded in the session.

        Returns
        -------
        CaptureResult
            The session, warnings and file path; ``path`` is None when Word
            had no open documents and nothing was saved.
        """
        session, warnings = self._snapshot(name, kind)
        # An empty Word has nothing worth saving.
        if not session.documents:
            return CaptureResult(session=session, warnings=warnings, path=None)
        return CaptureResult(session=session, warnings=warnings, path=self._save_new(session))

    # ---- restore ---------------------------------------------------------

    def restore(
        self,
        selector: str,
        *,
        only: list[str] | None = None,
        start_word: bool | None = None,
        restore_position: bool | None = None,
        dry_run: bool = False,
        progress: Callable[[RestoreResult], None] | None = None,
    ) -> RestoreReport:
        """Reopen the documents of a session in Word and report each outcome.

        Parameters
        ----------
        selector : str
            Session selector understood by ``SessionStore.get``.
        only : list[str] | None
            Globs matched case-insensitively against full paths and file
            names; only matching documents are restored.
        start_word : bool | None
            Start Word if needed; defaults to ``settings.restore.start_word``.
        restore_position : bool | None
            Move cursors back; defaults to ``settings.restore.restore_position``.
        dry_run : bool
            Report what would happen without any Word call.
        progress : Callable[[RestoreResult], None] | None
            Called after each document.

        Returns
        -------
        RestoreReport
            One result per selected document, active document last.

        Raises
        ------
        RestoreInProgress
            If another restore is running.
        WordUnavailable
            If Word is not running and may not be started.
        """
        # Only one restore at a time; the flag is cleared again in ``finally``.
        with self._restore_lock:
            if self._restoring:
                raise RestoreInProgress("a restore is already in progress")
            self._restoring = True
        try:
            return self._restore(
                selector, only, start_word, restore_position, dry_run=dry_run, progress=progress
            )
        finally:
            self._restoring = False

    # ---- listing and editing --------------------------------------------

    def list_sessions(self, *, kind: SessionKind | None = None) -> list[Session]:
        """Return stored sessions newest first, optionally of one kind."""
        sessions = self.store.list()
        return [s for s in sessions if kind is None or s.kind == kind]

    def get(self, selector: str) -> Session:
        """Resolve a selector to a session."""
        return self.store.get(selector)

    def revision(self, selector: str) -> str:
        """Return the revision (file digest) of the selected session."""
        return self.store.revision(self.store.get(selector).id)

    def update(
        self,
        selector: str,
        *,
        expected_revision: str | None = None,
        name: str | None = None,
        pinned: bool | None = None,
        notes: str | None = None,
        remove_paths: list[str] | None = None,
    ) -> Session:
        """Change the given fields of a session and save it.

        Parameters
        ----------
        selector : str
            Session selector.
        expected_revision : str | None
            When given, must equal the stored revision.
        name : str | None
            New name; None leaves it unchanged.
        pinned : bool | None
            New pinned flag; None leaves it unchanged.
        notes : str | None
            New notes; None leaves them unchanged.
        remove_paths : list[str] | None
            Document paths to drop, compared case-insensitively.

        Returns
        -------
        Session
            The saved session; its id never changes.

        Raises
        ------
        RevisionConflict
            If ``expected_revision`` is stale.
        """
        session = self.store.get(selector)

        # Refuse to overwrite edits made since the caller read the session.
        if expected_revision is not None and expected_revision != self.store.revision(session.id):
            raise RevisionConflict(f"session {session.id} changed since it was read")

        # Apply only the fields that were given.
        changes: dict[str, object] = {}
        if name is not None:
            changes["name"] = name
        if pinned is not None:
            changes["pinned"] = pinned
        if notes is not None:
            changes["notes"] = notes
        if remove_paths is not None:
            doomed = {p.casefold() for p in remove_paths}
            changes["documents"] = [d for d in session.documents if d.path.casefold() not in doomed]
        updated = session.model_copy(update=changes)

        self.store.save(updated)
        self.events.publish({"type": "session_updated", "session_id": updated.id})
        return updated

    def delete(self, selector: str, *, purge: bool = False) -> None:
        """Move the selected session to the trash, or delete it with ``purge``."""
        session = self.store.get(selector)
        self.store.delete(session.id, purge=purge)
        self.events.publish({"type": "session_deleted", "session_id": session.id})

    def prune(self, keep: int | None = None) -> list[str]:
        """Trash old automatic sessions, keeping ``keep`` (default from settings)."""
        return self.store.prune(self.settings.autosave.keep if keep is None else keep)

    def import_legacy(self, dirs: list[Path] | None = None) -> ImportSummary:
        """Import sessions written by the old tools (default: their usual folders)."""
        return legacy.import_legacy(
            self.store, dirs if dirs is not None else legacy.default_legacy_dirs()
        )

    def diff(self, a: str, b: str) -> SessionDiff:
        """Compare the document paths of two sessions, ignoring case."""
        first = [d.path for d in self.store.get(a).documents]
        second = [d.path for d in self.store.get(b).documents]
        first_keys = {p.casefold() for p in first}
        second_keys = {p.casefold() for p in second}
        return SessionDiff(
            added=[p for p in second if p.casefold() not in first_keys],
            removed=[p for p in first if p.casefold() not in second_keys],
        )

    # ---- autosave --------------------------------------------------------

    def autosave_tick(self) -> Session | None:
        """Save an automatic session if something changed, then prune.

        Returns
        -------
        Session | None
            The saved session, or None when skipped or when Word failed (an
            ``autosave_failed`` event is published in that case).
        """
        # Skip silently while restoring: Word is busy and changing.
        if self._restoring:
            return None
        try:
            # Never start Word for an autosave.
            if not self.word_info().running:
                return None
            session, _warnings = self._snapshot(None, "auto")
            if not session.documents:
                return None

            # Skip when nothing changed since the newest automatic session.
            if self.settings.autosave.only_on_change:
                newest = next((s for s in self.store.list() if s.kind == "auto"), None)
                if newest is not None and newest.fingerprint() == session.fingerprint():
                    return None

            self._save_new(session)
            self.prune()
            return session
        except WordError as exc:
            _log.warning("autosave failed: %s", exc)
            self.events.publish({"type": "autosave_failed", "message": str(exc)})
            return None

    def close(self) -> None:
        """Stop the Word worker."""
        self._worker.stop()

    # ---- internals -------------------------------------------------------

    def _snapshot(self, name: str | None, kind: SessionKind) -> tuple[Session, list[str]]:
        """Read Word and build an unsaved session plus capture warnings."""
        documents = self.current()
        now = self._clock()

        # Choose the default name from the kind and the capture time.
        if name is None:
            prefix = "Autosave" if kind == "auto" else "Session"
            name = f"{prefix} {now:%Y-%m-%d %H:%M}"

        # Warn about documents that will not survive a restore.
        warnings: list[str] = []
        for doc in documents:
            if doc.location == "unsaved":
                warnings.append(f"{doc.path} was never saved and cannot be restored")
            if doc.had_unsaved_changes:
                warnings.append(f"{doc.path} has unsaved changes that are not part of the session")
        if not documents:
            warnings.append("Word has no open documents")

        # Only reserve an id and ask for the version when there is something to save.
        version = ""
        session_id = ""
        if documents:
            version = self.word_info().version
            session_id = self.store.new_id(now, name)
        session = Session(
            id=session_id,
            name=name,
            kind=kind,
            created_at=now,
            host=self._host,
            word_version=version,
            documents=documents,
        )
        return session, warnings

    def _save_new(self, session: Session) -> Path:
        """Write a freshly captured session and announce it."""
        path = self.store.save(session)
        self.events.publish(
            {"type": "session_saved", "session_id": session.id, "kind": session.kind}
        )
        return path

    def _restore(
        self,
        selector: str,
        only: list[str] | None,
        start_word: bool | None,
        restore_position: bool | None,
        *,
        dry_run: bool,
        progress: Callable[[RestoreResult], None] | None,
    ) -> RestoreReport:
        """Run a restore; the caller holds the in-progress flag."""
        session = self.store.get(selector)
        if start_word is None:
            start_word = self.settings.restore.start_word
        if restore_position is None:
            restore_position = self.settings.restore.restore_position

        # Apply the ``only`` globs to full paths and to file names.
        documents = session.documents
        if only is not None:
            patterns = [p.casefold() for p in only]
            documents = [
                d
                for d in documents
                if any(
                    fnmatch.fnmatchcase(d.path.casefold(), p)
                    or fnmatch.fnmatchcase(ntpath.basename(d.path).casefold(), p)
                    for p in patterns
                )
            ]

        # Open the active document last so it ends up in front.
        ordered = [d for d in documents if not d.active] + [d for d in documents if d.active]

        # Documents that never reach Word are settled without a Word call.
        verdicts: dict[int, RestoreResult] = {}
        for index, doc in enumerate(ordered):
            if doc.location == "unsaved":
                verdicts[index] = RestoreResult(
                    path=doc.path, status="skipped", message="never saved"
                )
            elif doc.location in ("local", "unc") and not self._path_exists(doc.path):
                verdicts[index] = RestoreResult(
                    path=doc.path, status="missing", message="file not found"
                )
            elif dry_run:
                verdicts[index] = RestoreResult(
                    path=doc.path, status="skipped", message="dry run: would open"
                )

        # Connect once, before anything is reported as attempted.
        if len(verdicts) < len(ordered):
            self._worker.call(lambda b: b.connect(start_if_needed=bool(start_word)))

        total = len(ordered)
        self.events.publish({"type": "restore_started", "session_id": session.id, "total": total})
        report = RestoreReport(session_id=session.id, dry_run=dry_run)
        last_opened: str | None = None

        # Process documents one by one; a failure never stops the loop.
        for index, doc in enumerate(ordered):
            result = verdicts.get(index)
            if result is None:
                result = self._open_one(doc, bool(restore_position))
                if result.status in ("opened", "already_open"):
                    last_opened = doc.path
            report.results.append(result)
            if progress is not None:
                progress(result)
            self.events.publish(
                {
                    "type": "restore_progress",
                    "session_id": session.id,
                    "result": result.model_dump(mode="json"),
                    "index": index,
                    "total": total,
                }
            )

        # Bring the last successfully opened document to the front.
        if last_opened is not None:
            target = last_opened
            try:
                self._worker.call(lambda b: b.activate(target))
            except WordError:
                _log.warning("could not activate %s", target)

        self.events.publish(
            {
                "type": "restore_finished",
                "session_id": session.id,
                "report": report.model_dump(mode="json"),
            }
        )
        return report

    def _open_one(self, doc: DocumentState, restore_position: bool) -> RestoreResult:
        """Open one document in Word and translate the outcome into a result."""

        def work(backend: WordBackend) -> RestoreResult:
            outcome = backend.open_document(doc)
            message = ""
            # A cursor failure keeps the open status but is reported.
            if restore_position:
                try:
                    backend.restore_position(doc)
                except WordError as exc:
                    message = f"position not restored: {exc}"
            return RestoreResult(path=doc.path, status=outcome, message=message)

        try:
            return self._worker.call(work)
        except DocumentMissing as exc:
            return RestoreResult(path=doc.path, status="missing", message=str(exc))
        except DocumentLocked as exc:
            return RestoreResult(path=doc.path, status="locked", message=str(exc))
        except WordError as exc:
            return RestoreResult(path=doc.path, status="failed", message=str(exc))


def open_service(*, settings: Settings | None = None, fake: bool = False) -> SessionService:
    """Build a started ``SessionService`` for the real or the demo Word.

    Parameters
    ----------
    settings : Settings | None
        Settings to use; defaults to ``load_settings()``.
    fake : bool
        Use an in-memory fake Word with three demo documents.

    Returns
    -------
    SessionService
        A service whose worker is already running; call ``close()`` when done.
    """
    if settings is None:
        settings = load_settings()
    store = SessionStore(resolve_sessions_dir(settings, app_paths()))

    # The demo backend never touches real Word or the real file system.
    path_exists: Callable[[str], bool] | None = None
    if fake:
        from word_session.word.fake import FakeDocument, FakeWordBackend

        names = ("thesis", "notes", "todo")
        demo = FakeWordBackend(documents=[FakeDocument(path=f"C:\\Demo\\{n}.docx") for n in names])

        def factory() -> WordBackend:
            return demo

        path_exists = _always_exists
    else:
        # Imported lazily: the COM module is only needed for real Word.
        from word_session.word.com import ComWordBackend

        def factory() -> WordBackend:
            return ComWordBackend()

    worker = ComWorker(factory, call_timeout=settings.restore.open_timeout_s)
    worker.start()
    return SessionService(store, worker, settings, path_exists=path_exists)


def _always_exists(path: str) -> bool:
    """Pretend every path exists (used by the demo service)."""
    return True
