"""Pure data types for Word sessions, restore reports and the session file format v1.

Call ``Session.model_validate(data)`` to read a session file and
``session.model_dump(mode="json")`` to produce one. The module performs no
filesystem, Word or logging access. Unknown fields on sessions and documents
survive a validate/dump round trip so newer files are not damaged by older
versions.
"""

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Location = Literal["local", "unc", "url", "unsaved"]
SessionKind = Literal["manual", "auto", "imported"]
RestoreStatus = Literal["opened", "already_open", "missing", "locked", "failed", "skipped"]


class Position(BaseModel):
    """Describe where the cursor was in a document."""

    start: int | None = None  # Selection.Start (character offset)
    end: int | None = None  # Selection.End (character offset)
    page: int | None = None  # 1-based; None if Word reported <= 0
    line: int | None = None  # 1-based line on that page


class WindowState(BaseModel):
    """Describe the state of a document window."""

    state: Literal["normal", "maximized", "minimized"] | None = None


class DocumentState(BaseModel):
    """Describe one open document captured in a session.

    Unknown fields are preserved.
    """

    model_config = ConfigDict(extra="allow")

    path: str
    location: Location
    position: Position = Field(default_factory=Position)
    active: bool = False
    read_only: bool = False
    had_unsaved_changes: bool = False
    window: WindowState | None = None


class Session(BaseModel):
    """Describe a saved set of open Word documents (session file format v1).

    Attributes
    ----------
    id : str
        Timestamp-and-slug identifier; also the file stem.
    created_at : datetime
        Timezone-aware creation time.
    documents : list[DocumentState]
        Captured documents in capture order.

    Raises
    ------
    ValueError
        If ``created_at`` is a naive datetime.
    """

    model_config = ConfigDict(extra="allow")

    format: Literal["word-session"] = "word-session"
    version: Literal[1] = 1
    id: str
    name: str
    kind: SessionKind
    pinned: bool = False
    created_at: datetime
    host: str = ""
    word_version: str = ""
    notes: str = ""
    documents: list[DocumentState]

    @field_validator("created_at")
    @classmethod
    def _require_aware(cls, value: datetime) -> datetime:
        """Reject naive datetimes so stored timestamps are unambiguous."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware (include a UTC offset)")
        return value

    def fingerprint(self) -> str:
        """Return a SHA-256 hex digest of the document set and cursor positions.

        Ignores id, name and timestamps, so it detects whether anything worth
        autosaving changed. Document order matters and paths compare
        case-insensitively.
        """
        # Reduce each document to the fields that matter for change detection.
        items = [
            [d.path.casefold(), d.position.start, d.position.end, d.active] for d in self.documents
        ]
        canonical = json.dumps(items, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RestoreResult(BaseModel):
    """Describe the outcome of restoring one document."""

    path: str
    status: RestoreStatus
    message: str = ""


class RestoreReport(BaseModel):
    """Collect per-document outcomes of restoring a session."""

    session_id: str
    dry_run: bool = False
    results: list[RestoreResult] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return True when no result is missing, locked or failed."""
        bad = {"missing", "locked", "failed"}
        return not any(r.status in bad for r in self.results)


def classify_location(path: str) -> Location:
    """Classify a document path as local, UNC, URL or unsaved.

    Parameters
    ----------
    path : str
        The full name Word reports for a document.

    Returns
    -------
    Location
        ``"url"`` for http(s), ``"unc"`` for double-backslash prefixes,
        ``"local"`` for drive-letter paths and ``"unsaved"`` for anything else.

    Examples
    --------
    Basic usage:

    >>> classify_location("C:/x.docx")
    'local'
    >>> classify_location("Document1")
    'unsaved'
    """
    # Check the most specific prefixes first; anything unrecognised is unsaved.
    if path.lower().startswith(("http://", "https://")):
        return "url"
    if path.startswith("\\\\"):
        return "unc"
    if re.match(r"^[A-Za-z]:[\\/]", path):
        return "local"
    return "unsaved"


def slugify(name: str) -> str:
    """Turn a session name into a lowercase ASCII slug of at most 40 characters.

    Parameters
    ----------
    name : str
        Free-form session name.

    Returns
    -------
    str
        The slug, or ``"session"`` when nothing usable remains.

    Examples
    --------
    Basic usage:

    >>> slugify("Thèse — chapitre 3")
    'these-chapitre-3'
    """
    # Fold accents to ASCII, then collapse every other run into one hyphen.
    ascii_text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    slug = slug[:40].rstrip("-")
    return slug or "session"


def make_session_id(created_at: datetime, name: str) -> str:
    """Build a session id of the form ``YYYYMMDDTHHMMSS-slug``.

    Uniqueness is the store's responsibility.

    Examples
    --------
    Basic usage:

    >>> make_session_id(datetime(2026, 10, 31, 14, 30), "Thesis chapter 3")
    '20261031T143000-thesis-chapter-3'
    """
    return created_at.strftime("%Y%m%dT%H%M%S") + "-" + slugify(name)
