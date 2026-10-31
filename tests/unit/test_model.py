"""Tests for the pure data model."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from word_session.model import (
    DocumentState,
    Position,
    RestoreReport,
    RestoreResult,
    RestoreStatus,
    Session,
    classify_location,
    make_session_id,
    slugify,
)

PLAN_EXAMPLE = json.loads(
    r"""
{
  "format": "word-session",
  "version": 1,
  "id": "20261031T143000-thesis-chapter-3",
  "name": "Thesis chapter 3",
  "kind": "manual",
  "pinned": false,
  "created_at": "2026-10-31T14:30:00+01:00",
  "host": "LAPTOP-123",
  "word_version": "16.0",
  "notes": "",
  "documents": [
    {
      "path": "C:\\Users\\me\\Documents\\ch3.docx",
      "location": "local",
      "position": { "start": 18234, "end": 18234, "page": 12, "line": 7 },
      "active": true,
      "read_only": false,
      "had_unsaved_changes": false,
      "window": { "state": "maximized" }
    }
  ]
}
"""
)

TZ = timezone(timedelta(hours=1))


def make_session(
    paths: list[str] | None = None,
    *,
    name: str = "A",
    sid: str = "x",
    created: datetime | None = None,
    start: int | None = 1,
) -> Session:
    docs = [
        DocumentState(
            path=p, location=classify_location(p), position=Position(start=start, end=start)
        )
        for p in (paths or ["C:/a.docx", "C:/b.docx"])
    ]
    return Session(
        id=sid,
        name=name,
        kind="manual",
        created_at=created or datetime(2026, 1, 1, tzinfo=TZ),
        documents=docs,
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("C:/x.docx", "local"),
        ("c:\\x.docx", "local"),
        ("\\\\server\\share\\x.docx", "unc"),
        ("https://contoso.sharepoint.com/x.docx", "url"),
        ("HTTP://example.com/x.docx", "url"),
        ("Document1", "unsaved"),
        ("", "unsaved"),
        ("C:x.docx", "unsaved"),
    ],
)
def test_classify_location(path: str, expected: str) -> None:
    assert classify_location(path) == expected


def test_slugify_cases() -> None:
    assert slugify("Thèse — chapitre 3") == "these-chapitre-3"
    assert slugify("!!! ???") == "session"
    assert slugify("") == "session"
    long = slugify("word " * 30)
    assert len(long) <= 40
    assert not long.endswith("-")
    # Truncation landing on a hyphen must not leave a trailing one.
    assert slugify("a" * 39 + " b") == "a" * 39


def test_make_session_id_format() -> None:
    created = datetime(2026, 10, 31, 14, 30, tzinfo=TZ)
    assert make_session_id(created, "Thesis chapter 3") == "20261031T143000-thesis-chapter-3"


def test_naive_datetime_rejected_and_aware_accepted() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        Session(id="x", name="n", kind="manual", created_at=datetime(2026, 1, 1), documents=[])
    session = make_session()
    assert session.created_at.utcoffset() == timedelta(hours=1)


def test_plan_example_validates_and_round_trips() -> None:
    session = Session.model_validate(PLAN_EXAMPLE)
    assert session.documents[0].position.page == 12
    assert session.documents[0].window is not None
    assert session.documents[0].window.state == "maximized"
    dumped = session.model_dump(mode="json")
    assert dumped["created_at"] == "2026-10-31T14:30:00+01:00"
    assert dumped == PLAN_EXAMPLE


def test_unknown_fields_preserved() -> None:
    data = json.loads(json.dumps(PLAN_EXAMPLE))
    data["future"] = {"a": 1}
    data["documents"][0]["extra_doc_field"] = "keep"
    dumped = Session.model_validate(data).model_dump(mode="json")
    assert dumped["future"] == {"a": 1}
    assert dumped["documents"][0]["extra_doc_field"] == "keep"


def test_fingerprint_ignores_metadata() -> None:
    a = make_session(name="A", sid="1", created=datetime(2026, 1, 1, tzinfo=TZ))
    b = make_session(name="B", sid="2", created=datetime(2027, 5, 5, tzinfo=TZ))
    assert a.fingerprint() == b.fingerprint()
    assert len(a.fingerprint()) == 64


def test_fingerprint_detects_changes() -> None:
    base = make_session()
    assert base.fingerprint() != make_session(start=2).fingerprint()
    assert base.fingerprint() != make_session(["C:/a.docx"]).fingerprint()
    # Order matters.
    assert base.fingerprint() != make_session(["C:/b.docx", "C:/a.docx"]).fingerprint()
    # Active flag matters.
    active = make_session()
    active.documents[0].active = True
    assert base.fingerprint() != active.fingerprint()


def test_fingerprint_path_case_insensitive() -> None:
    upper = make_session(["C:/A.DOCX"])
    lower = make_session(["c:/a.docx"])
    assert upper.fingerprint() == lower.fingerprint()


@pytest.mark.parametrize(
    ("statuses", "ok"),
    [
        ([], True),
        (["opened", "already_open", "skipped"], True),
        (["opened", "missing"], False),
        (["locked"], False),
        (["failed", "opened"], False),
    ],
)
def test_restore_report_ok(statuses: list[RestoreStatus], ok: bool) -> None:
    report = RestoreReport(
        session_id="x",
        results=[RestoreResult(path=f"p{i}", status=s) for i, s in enumerate(statuses)],
    )
    assert report.ok is ok
