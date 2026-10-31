"""Read session files written by the old Python and PowerShell tools and import them.

Call ``read_session_file(path)`` to convert one legacy (or version 1) file into a
``Session``, and ``import_legacy(store, dirs)`` to import every file found in the
given folders. Imports are idempotent: each imported session records the SHA-256
of its source file, and files whose hash is already present in the store are
skipped. Source files are only ever read, never modified or moved.
"""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from word_session.model import DocumentState, Position, Session, classify_location, make_session_id
from word_session.store import SessionStore


class LegacyFormatError(Exception):
    """Report that a file is unreadable or not in any known session format."""


@dataclass
class ImportSummary:
    """Describe the outcome of a legacy import run.

    Attributes
    ----------
    imported : list[str]
        Ids of the newly created sessions.
    skipped : list[Path]
        Source files already imported earlier.
    errors : list[tuple[Path, str]]
        Source files that could not be converted, with the reason.
    """

    imported: list[str] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)


def default_legacy_dirs() -> list[Path]:
    """Return the folders the old tools wrote to, ``~/.word-session`` and ``~/.word-sessions``."""
    home = Path.home()
    return [home / ".word-session", home / ".word-sessions"]


def import_legacy(store: SessionStore, dirs: Iterable[Path]) -> ImportSummary:
    """Import every legacy session file in ``dirs`` into ``store``.

    Parameters
    ----------
    store : SessionStore
        Destination store.
    dirs : Iterable[Path]
        Folders to scan non-recursively for ``*.json`` files; missing folders
        are ignored.

    Returns
    -------
    ImportSummary
        New session ids, already-imported files and per-file errors.

    Notes
    -----
    Errors are collected rather than raised. Source files are never modified.

    Examples
    --------
    Basic usage:

    >>> summary = import_legacy(SessionStore(Path("sessions")), [Path("missing")])
    >>> summary.imported
    []
    """
    summary = ImportSummary()

    # Remember which source hashes the store already holds so reruns are no-ops.
    known_hashes: set[str] = set()
    for session in store.list():
        origin = (session.model_extra or {}).get("imported_from")
        if isinstance(origin, dict) and isinstance(origin.get("sha256"), str):
            known_hashes.add(origin["sha256"])

    # Visit files in a deterministic order, converting and saving each one.
    for directory in dirs:
        if not directory.is_dir():
            continue
        for path in sorted(p for p in directory.glob("*.json") if p.is_file()):
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if digest in known_hashes:
                    summary.skipped.append(path)
                    continue
                session = read_session_file(path)
                # Version 1 files carry no provenance; add it so reruns skip them.
                if "imported_from" not in (session.model_extra or {}):
                    origin = {"path": str(path), "sha256": digest, "format": "v1"}
                    session = session.model_copy(update={"imported_from": origin})
                # Give the session a store-unique id before saving.
                session.id = store.new_id(session.created_at, session.name)
                store.save(session)
            except (LegacyFormatError, OSError) as exc:
                summary.errors.append((path, str(exc)))
                continue
            known_hashes.add(digest)
            summary.imported.append(session.id)
    return summary


def read_session_file(path: Path) -> Session:
    """Convert one session file of any known format into a ``Session``.

    Parameters
    ----------
    path : Path
        A version 1 file, a Python v0 file (key ``"word-session:"``) or a
        PowerShell file (key ``"sessions"``).

    Returns
    -------
    Session
        For legacy files, an ``imported`` session whose ``imported_from`` extra
        field records the source path, SHA-256 and format.

    Raises
    ------
    LegacyFormatError
        If the file cannot be read, decoded or parsed, or matches no format.

    Examples
    --------
    Basic usage:

    >>> session = read_session_file(Path("20241123T101500 word-session.json"))  # doctest: +SKIP
    """
    # Read and decode the bytes, tolerating the encodings the old tools used.
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise LegacyFormatError(f"{path}: cannot read file: {exc}") from exc
    text = _decode(raw, path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LegacyFormatError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LegacyFormatError(f"{path}: expected a JSON object at the top level")

    # Version 1 files pass straight through validation.
    if data.get("format") == "word-session":
        try:
            return Session.model_validate(data)
        except ValidationError as exc:
            raise LegacyFormatError(f"{path}: invalid session: {exc}") from exc

    # Pick the legacy format from its distinctive top-level key.
    if "word-session:" in data:
        items, fmt = data["word-session:"], "python-v0"
        line_key, page_key = "Line", "Page"
    elif "sessions" in data:
        items, fmt = data["sessions"], "powershell"
        line_key, page_key = "cursorLine", "pageNumber"
    else:
        raise LegacyFormatError(f"{path}: unknown session format; top-level keys: {sorted(data)}")
    # PowerShell collapses a one-element list into a bare object.
    if isinstance(items, dict):
        items = [items]
    if items is None:
        items = []
    if not isinstance(items, list):
        raise LegacyFormatError(f"{path}: document list has unexpected type")

    # Build the documents; the active document is unknown in legacy files.
    documents: list[DocumentState] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("FullName"), str):
            raise LegacyFormatError(f"{path}: document entry without a FullName string")
        full_name = item["FullName"]
        position = Position(page=_positive(item.get(page_key)), line=_positive(item.get(line_key)))
        documents.append(
            DocumentState(
                path=full_name,
                location=classify_location(full_name),
                position=position,
                active=False,
            )
        )

    # Construct the imported session, recording where it came from.
    created_at = _created_at(path)
    name = "Imported " + created_at.strftime("%Y-%m-%d %H:%M")
    imported_from = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "format": fmt}
    return Session.model_validate(
        {
            "id": make_session_id(created_at, name),
            "name": name,
            "kind": "imported",
            "created_at": created_at,
            "documents": [d.model_dump() for d in documents],
            "imported_from": imported_from,
        }
    )


# ---- helpers -----------------------------------------------------------


def _decode(raw: bytes, path: Path) -> str:
    """Decode file bytes using the BOM when present, else UTF-8, else cp1252."""
    if raw.startswith(b"\xff\xfe"):
        encodings, body = ["utf-16-le"], raw[2:]
    elif raw.startswith(b"\xfe\xff"):
        encodings, body = ["utf-16-be"], raw[2:]
    elif raw.startswith(b"\xef\xbb\xbf"):
        encodings, body = ["utf-8-sig"], raw
    else:
        encodings, body = ["utf-8", "cp1252"], raw
    for encoding in encodings:
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise LegacyFormatError(f"{path}: cannot decode file as {' or '.join(encodings)}")


def _positive(value: Any) -> int | None:
    """Return ``value`` if it is a positive integer, else ``None``."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _created_at(path: Path) -> datetime:
    """Take the creation time from the file name's timestamp, else from the mtime."""
    try:
        return datetime.strptime(path.name[:15], "%Y%m%dT%H%M%S").astimezone()
    except ValueError:
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone()
