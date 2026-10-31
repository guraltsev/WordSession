"""Persist Word sessions as JSON files with atomic writes, selectors and a trash folder.

Create a ``SessionStore`` for a directory and call ``save(...)``, ``get(...)``,
``list()``, ``delete(...)`` and ``prune(...)``. Every session lives in
``<id>.json`` directly inside the store root; deleted sessions move to a
``trash`` subfolder so they can be recovered by hand. The module never touches
Word and reads only version 1 session files.
"""

import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from word_session.model import Session, make_session_id

logger = logging.getLogger(__name__)

# Aliases so the ``list`` method does not shadow the builtin inside annotations.
_SessionList = list[Session]
_InvalidList = list[tuple[Path, str]]
_PathList = list[Path]


class StoreError(Exception):
    """Report a failure to read, write or locate a stored session."""


class SessionNotFound(StoreError):
    """Report that no stored session matches a selector or id."""


class AmbiguousSelector(StoreError):
    """Report that a selector matches several sessions.

    Attributes
    ----------
    candidates : list[str]
        Ids of every matching session.
    """

    def __init__(self, message: str, candidates: list[str]) -> None:
        super().__init__(message)
        self.candidates = candidates


class SessionStore:
    """Store sessions as JSON files in one directory.

    Parameters
    ----------
    root : Path
        Sessions directory; created on the first write.

    Attributes
    ----------
    root : Path
        Sessions directory.
    trash_dir : Path
        ``root / "trash"``, where deleted and pruned sessions are moved.

    Methods
    -------
    save
        Write a session atomically.
    get
        Resolve a selector to a session.
    list
        Return all valid sessions, newest first.
    delete
        Move a session to the trash or remove it outright.
    prune
        Trash old unpinned automatic sessions.

    Examples
    --------
    Basic usage:

    >>> store = SessionStore(Path("sessions"))
    >>> store.trash_dir.name
    'trash'
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.trash_dir = root / "trash"

    # ---- writing -------------------------------------------------------

    def new_id(self, created_at: datetime, name: str) -> str:
        """Return an unused session id for a new session.

        Parameters
        ----------
        created_at : datetime
            Creation time used for the id prefix.
        name : str
            Session name used for the id slug.

        Returns
        -------
        str
            ``make_session_id(...)``, with ``-2``, ``-3``, ... appended while
            a file of that name exists in the root or the trash.
        """
        # Probe both folders so a trashed id is never reused.
        base = make_session_id(created_at, name)
        candidate = base
        counter = 2
        while (self.root / f"{candidate}.json").exists() or (
            self.trash_dir / f"{candidate}.json"
        ).exists():
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    def save(self, session: Session) -> Path:
        """Write a session to ``<id>.json`` atomically, replacing any existing file.

        Parameters
        ----------
        session : Session
            Session to persist.

        Returns
        -------
        Path
            Path of the written file.

        Raises
        ------
        StoreError
            If the session id is not a plain file name.
        """
        path = self.path_for(session.id)
        tmp = path.with_name(path.name + ".tmp")

        # Serialize first so a model error leaves the filesystem untouched.
        text = json.dumps(session.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"

        # Write a temp file in the same directory, flush it to disk and swap it
        # in; remove the temp file on any failure.
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            with tmp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            tmp.replace(path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return path

    def delete(self, session_id: str, *, purge: bool = False) -> None:
        """Move a session to the trash, or delete it when ``purge`` is true.

        Parameters
        ----------
        session_id : str
            Id of the session to remove.
        purge : bool
            Delete outright instead of moving to the trash.

        Raises
        ------
        SessionNotFound
            If no such session file exists.
        """
        source = self.path_for(session_id)
        if not source.is_file():
            raise SessionNotFound(f"no session with id {session_id!r} in {self.root}")

        # Purge removes the file; otherwise move it, overwriting an older
        # trashed file of the same name.
        if purge:
            source.unlink()
            return
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        source.replace(self.trash_dir / source.name)

    def prune(self, keep: int) -> list[str]:
        """Trash all but the newest ``keep`` unpinned automatic sessions.

        Parameters
        ----------
        keep : int
            Number of newest prunable sessions to retain; must be >= 0.

        Returns
        -------
        list[str]
            Ids of the sessions moved to the trash.

        Raises
        ------
        ValueError
            If ``keep`` is negative.

        Notes
        -----
        Manual, imported and pinned sessions are never pruned.
        """
        if keep < 0:
            raise ValueError(f"keep must be >= 0, got {keep}")

        # ``list()`` is newest first, so everything after the first ``keep``
        # prunable sessions is surplus.
        prunable = [s for s in self.list() if s.kind == "auto" and not s.pinned]
        removed = [s.id for s in prunable[keep:]]
        for session_id in removed:
            self.delete(session_id)
        return removed

    # ---- reading -------------------------------------------------------

    def load_file(self, path: Path) -> Session:
        """Read and validate a version 1 session file.

        Parameters
        ----------
        path : Path
            File to read.

        Returns
        -------
        Session
            The validated session.

        Raises
        ------
        StoreError
            If the file is unreadable, not JSON or fails validation; the
            message names the path and the reason.
        """
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Session.model_validate(data)
        except (OSError, UnicodeDecodeError) as exc:
            raise StoreError(f"{path}: cannot read file: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise StoreError(f"{path}: invalid JSON: {exc}") from exc
        except ValidationError as exc:
            raise StoreError(f"{path}: invalid session: {exc}") from exc

    def list(self) -> _SessionList:
        """Return every valid stored session, newest first.

        Invalid files are skipped with a logged warning; see ``list_invalid``.
        """
        sessions: _SessionList = []
        for path in self._session_files():
            try:
                sessions.append(self.load_file(path))
            except StoreError as exc:
                logger.warning("skipping invalid session file: %s", exc)
        sessions.sort(key=lambda s: s.id, reverse=True)
        return sessions

    def list_invalid(self) -> _InvalidList:
        """Return ``(path, error text)`` for every unreadable session file."""
        invalid: _InvalidList = []
        for path in self._session_files():
            try:
                self.load_file(path)
            except StoreError as exc:
                invalid.append((path, str(exc)))
        return invalid

    def get(self, selector: str) -> Session:
        """Resolve a selector to a session.

        Parameters
        ----------
        selector : str
            One of, in order: ``latest``, ``latest-manual``, ``latest-auto``;
            ``-N`` for the N-th newest; a path to an existing ``.json`` file;
            an exact id; an exact name (case-insensitive); a unique id prefix
            of at least four characters.

        Returns
        -------
        Session
            The matching session.

        Raises
        ------
        SessionNotFound
            If nothing matches or the store is empty.
        AmbiguousSelector
            If a name or id prefix matches several sessions.
        """
        sessions = self.list()
        if not sessions:
            raise SessionNotFound(f"no sessions in {self.root}")

        # Rule 1: "latest" and its per-kind variants.
        kinds = {"latest": None, "latest-manual": "manual", "latest-auto": "auto"}
        if selector in kinds:
            kind = kinds[selector]
            for session in sessions:
                if kind is None or session.kind == kind:
                    return session
            raise SessionNotFound(f"no sessions match selector {selector!r}")

        # Rule 2: "-N" counts from the newest session.
        if selector.startswith("-") and selector[1:].isdecimal() and int(selector[1:]) >= 1:
            index = int(selector[1:])
            if index > len(sessions):
                raise SessionNotFound(
                    f"selector {selector!r}: only {len(sessions)} session(s) in {self.root}"
                )
            return sessions[index - 1]

        # Rule 3: an existing .json file, wherever it is.
        if selector.lower().endswith(".json") and Path(selector).is_file():
            return self.load_file(Path(selector))

        # Rule 4: exact id.
        for session in sessions:
            if session.id == selector:
                return session

        # Rule 5: exact name, ignoring case.
        by_name = [s for s in sessions if s.name.casefold() == selector.casefold()]
        if len(by_name) == 1:
            return by_name[0]
        if by_name:
            ids = [s.id for s in by_name]
            raise AmbiguousSelector(f"name {selector!r} matches several sessions: {ids}", ids)

        # Rule 6: unique id prefix of at least four characters.
        if len(selector) >= 4:
            by_prefix = [s for s in sessions if s.id.startswith(selector)]
            if len(by_prefix) == 1:
                return by_prefix[0]
            if by_prefix:
                ids = [s.id for s in by_prefix]
                raise AmbiguousSelector(f"prefix {selector!r} matches several sessions: {ids}", ids)

        raise SessionNotFound(f"no session matches selector {selector!r}")

    def path_for(self, session_id: str) -> Path:
        """Return the file path for a session id.

        Raises
        ------
        StoreError
            If the id is empty or contains path separators.
        """
        # Ids become file names, so refuse anything that could leave the root.
        if not session_id or Path(session_id).name != session_id or session_id in {".", ".."}:
            raise StoreError(f"invalid session id: {session_id!r}")
        return self.root / f"{session_id}.json"

    def revision(self, session_id: str) -> str:
        """Return the SHA-256 hex digest of a session file's bytes.

        Raises
        ------
        SessionNotFound
            If no such session file exists.
        """
        path = self.path_for(session_id)
        if not path.is_file():
            raise SessionNotFound(f"no session with id {session_id!r} in {self.root}")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    # ---- helpers -------------------------------------------------------

    def _session_files(self) -> _PathList:
        """Return the ``*.json`` files directly in the root, in name order."""
        if not self.root.is_dir():
            return []
        return sorted(p for p in self.root.glob("*.json") if p.is_file())
