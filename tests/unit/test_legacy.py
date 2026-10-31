"""Tests for the legacy session readers and the idempotent importer."""

import os
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from word_session.legacy import (
    LegacyFormatError,
    default_legacy_dirs,
    import_legacy,
    read_session_file,
)
from word_session.store import SessionStore

FIXTURES = Path(__file__).parent.parent / "fixtures" / "legacy"
PY_V0 = FIXTURES / "20241123T101500 word-session.json"
PY_CP1252 = FIXTURES / "20240102T030405 word-session-cp1252.json"
PS_UTF16 = FIXTURES / "20250301T080910-Word-session.json"
PS_UTF8 = FIXTURES / "20250302T111213-Word-session-utf8.json"
PS_SINGLE = FIXTURES / "powershell_single.json"


def test_python_v0_converts() -> None:
    session = read_session_file(PY_V0)
    assert session.kind == "imported"
    assert session.name == "Imported 2024-11-23 10:15"
    assert session.id.startswith("20241123T101500-")
    assert [d.path for d in session.documents] == [
        "C:\\Docs\\thesis.docx",
        "\\\\server\\share\\notes.docx",
    ]
    assert [d.location for d in session.documents] == ["local", "unc"]
    first, second = session.documents
    assert (first.position.page, first.position.line) == (3, 12)
    assert (second.position.page, second.position.line) == (None, None)
    assert first.position.start is None and first.position.end is None
    assert not any(d.active for d in session.documents)
    assert session.model_extra is not None
    origin = session.model_extra["imported_from"]
    assert origin["format"] == "python-v0"
    assert origin["path"] == str(PY_V0)
    assert len(origin["sha256"]) == 64


def test_cp1252_path_decodes() -> None:
    session = read_session_file(PY_CP1252)
    assert session.documents[0].path == "C:\\Docs\\caf\u00e9.docx"


def test_powershell_utf16_converts() -> None:
    session = read_session_file(PS_UTF16)
    assert [d.location for d in session.documents] == ["local", "unsaved"]
    assert (session.documents[0].position.page, session.documents[0].position.line) == (2, 7)
    assert session.model_extra is not None
    assert session.model_extra["imported_from"]["format"] == "powershell"


def test_powershell_utf8_and_single_object() -> None:
    assert len(read_session_file(PS_UTF8).documents) == 2
    single = read_session_file(PS_SINGLE)
    assert [d.path for d in single.documents] == ["C:\\Docs\\solo.docx"]
    assert (single.documents[0].position.page, single.documents[0].position.line) == (9, 4)


def test_utf16_be_and_utf8_sig(tmp_path: Path) -> None:
    text = '{"sessions": [{"FullName": "C:\\\\a.docx", "cursorLine": 1, "pageNumber": 1}]}'
    be = tmp_path / "be.json"
    be.write_bytes(b"\xfe\xff" + text.encode("utf-16-be"))
    sig = tmp_path / "sig.json"
    sig.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    assert read_session_file(be).documents[0].path == "C:\\a.docx"
    assert read_session_file(sig).documents[0].path == "C:\\a.docx"


def test_v1_passes_through() -> None:
    session = read_session_file(FIXTURES / "v1.json")
    assert session.id == "20250101T000000-demo"
    assert session.kind == "manual"
    assert not (session.model_extra or {}).get("imported_from")


def test_invalid_v1_is_format_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"format": "word-session", "version": 1}')
    with pytest.raises(LegacyFormatError, match="invalid session"):
        read_session_file(bad)


def test_truncated_and_unknown_raise() -> None:
    with pytest.raises(LegacyFormatError, match="invalid JSON"):
        read_session_file(FIXTURES / "truncated.json")
    with pytest.raises(LegacyFormatError, match=r"unknown\.json.*\['bar', 'foo'\]"):
        read_session_file(FIXTURES / "unknown.json")


def test_other_malformed_inputs(tmp_path: Path) -> None:
    cases = {
        "list.json": "[1, 2]",
        "entry.json": '{"sessions": [1]}',
        "type.json": '{"sessions": 5}',
    }
    for name, text in cases.items():
        (tmp_path / name).write_text(text)
    (tmp_path / "undecodable.json").write_bytes(b"\xff\xfe\x00")
    for name in [*cases, "undecodable.json"]:
        with pytest.raises(LegacyFormatError):
            read_session_file(tmp_path / name)
    with pytest.raises(LegacyFormatError, match="cannot read"):
        read_session_file(tmp_path / "missing.json")


def test_empty_and_odd_position_values(tmp_path: Path) -> None:
    path = tmp_path / "odd.json"
    path.write_text(
        '{"word-session:": [{"FullName": "C:\\\\a.docx", "Line": "3", "Page": true},'
        ' {"FullName": "https://x/y.docx", "Line": 2.5, "Page": null}]}'
    )
    docs = read_session_file(path).documents
    assert all(d.position.line is None and d.position.page is None for d in docs)
    assert docs[1].location == "url"
    empty = tmp_path / "20250101T000000 empty.json"
    empty.write_text('{"sessions": null}')
    assert read_session_file(empty).documents == []


def test_created_at_from_name_and_mtime(tmp_path: Path) -> None:
    from_name = read_session_file(PY_V0).created_at
    assert from_name.tzinfo is not None
    assert from_name.replace(tzinfo=None) == datetime(2024, 11, 23, 10, 15, 0)

    path = tmp_path / "no-timestamp.json"
    path.write_text('{"sessions": []}')
    stamp = datetime(2023, 5, 6, 7, 8, 9).timestamp()
    os.utime(path, (stamp, stamp))
    from_mtime = read_session_file(path).created_at
    assert from_mtime.tzinfo is not None
    assert from_mtime.replace(tzinfo=None) == datetime(2023, 5, 6, 7, 8, 9)


def test_default_legacy_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert default_legacy_dirs() == [tmp_path / ".word-session", tmp_path / ".word-sessions"]


def _snapshot(folder: Path) -> dict[str, tuple[bytes, int]]:
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()}


def test_import_is_idempotent_and_leaves_sources_alone(tmp_path: Path) -> None:
    source = tmp_path / "src"
    shutil.copytree(FIXTURES, source)
    (source / "README.md").unlink()
    before = _snapshot(source)
    store = SessionStore(tmp_path / "store")

    first = import_legacy(store, [source, tmp_path / "does-not-exist"])
    assert len(first.imported) == 6  # five legacy files plus the v1 file
    assert first.skipped == []
    assert sorted(p.name for p, _ in first.errors) == ["truncated.json", "unknown.json"]
    assert len(store.list()) == 6

    second = import_legacy(store, [source])
    assert second.imported == []
    assert len(second.skipped) == 6
    assert len(second.errors) == 2

    assert _snapshot(source) == before


def test_import_duplicate_names_get_unique_ids(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    text = '{"sessions": [{"FullName": "C:\\\\a.docx"}]}'
    (source / "20250101T000000 a.json").write_text(text)
    (source / "20250101T000000 b.json").write_text(text + " ")
    store = SessionStore(tmp_path / "store")
    summary = import_legacy(store, [source])
    assert len(set(summary.imported)) == 2
