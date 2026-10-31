"""Run the command line against the Word instance the user left running."""

import json
import sys
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from word_session.cli import main
from word_session.model import DocumentState, Position, Session
from word_session.store import SessionStore
from word_session.word.backend import WordUnavailable
from word_session.word.com import ComWordBackend

from .conftest import last_json

pytestmark = pytest.mark.shared_word


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/'
    'package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.'
    'openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="'
    'application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.'
    'openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.'
    'openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://'
    'schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/></Relationships>'
)


def _write_docx(path: Path, paragraphs: int = 60) -> Path:
    """Write a minimal .docx without Word (never start Word near the user's)."""
    body = "".join(f"<w:p><w:r><w:t>Paragraph {i}</w:t></w:r></w:p>" for i in range(paragraphs))
    document = (
        '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.'
        f'openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr("word/document.xml", document)
    return path


def _paths(app: Any) -> list[str]:
    """Return the full names of all open documents."""
    return [str(app.Documents.Item(i).FullName) for i in range(1, app.Documents.Count + 1)]


@pytest.fixture
def attached(tmp_path: Path) -> Iterator[Any]:
    """Attach to the user's Word, then close only temp documents and re-activate."""
    if sys.platform != "win32":
        pytest.skip("COM needs Windows")
    import pythoncom

    pythoncom.CoInitialize()
    backend = ComWordBackend()
    try:
        try:
            backend.connect(start_if_needed=False)
        except WordUnavailable:
            pytest.skip("user's Word not reachable over COM (not in the ROT yet)")
        app = backend._app
        active = str(app.ActiveDocument.FullName) if app.Documents.Count else None
        before = _paths(app)
        try:
            yield app
        finally:
            root = str(tmp_path).casefold()
            for i in range(app.Documents.Count, 0, -1):
                document = app.Documents.Item(i)
                if str(document.FullName).casefold().startswith(root):
                    document.Close(0)
            if active is not None:
                for i in range(1, app.Documents.Count + 1):
                    if str(app.Documents.Item(i).FullName) == active:
                        app.Documents.Item(i).Activate()
            assert _paths(app) == before
    finally:
        backend.disconnect()
        pythoncom.CoUninitialize()


def test_current_lists_users_documents(
    attached: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--json", "--sessions-dir", str(tmp_path / "s"), "current"]) == 0
    documents = last_json(capsys)
    assert isinstance(documents, list)
    assert len(documents) == attached.Documents.Count


def test_restore_temp_documents_then_already_open(
    attached: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    docs = [_write_docx(tmp_path / "docs" / f"shared{n}.docx") for n in (1, 2)]
    sessions = tmp_path / "sessions"
    session = Session(
        id="2026-01-01T000000-shared",
        name="shared",
        kind="manual",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        host="h",
        word_version="16.0",
        documents=[
            DocumentState(path=str(p.resolve()), location="local", position=Position(start=10))
            for p in docs[:2]
        ],
    )
    SessionStore(sessions).save(session)
    capsys.readouterr()

    args = ["--json", "--sessions-dir", str(sessions), "restore", "shared", "--no-start"]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert [r["status"] for r in first["results"]] == ["opened", "opened"]

    assert main(args) == 0
    second = json.loads(capsys.readouterr().out)
    assert [r["status"] for r in second["results"]] == ["already_open", "already_open"]
