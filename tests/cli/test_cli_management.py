"""Tests for the session management commands and the first-run import message."""

import json
import logging
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from word_session import shortcut
from word_session.cli import EXIT_ERROR, EXIT_NOT_FOUND, EXIT_USAGE, main
from word_session.service import SessionService
from word_session.word.fake import FakeDocument, FakeWordBackend

Run = Callable[..., tuple[int, str, str]]


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """Remove log handlers installed by a CLI run so they never leak between tests."""
    root = logging.getLogger()
    before = list(root.handlers)
    yield
    for handler in [h for h in root.handlers if h not in before]:
        root.removeHandler(handler)
        handler.close()


@pytest.fixture
def run(service: SessionService, capsys: pytest.CaptureFixture[str]) -> Run:
    """Return a function running the CLI against the shared service."""
    service.close = lambda: None  # type: ignore[method-assign]

    def _run(*argv: str) -> tuple[int, str, str]:
        capsys.readouterr()
        code = main(list(argv), service_factory=lambda args: service)
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


@pytest.fixture
def saved(service: SessionService) -> str:
    """Return the id of one manual session named ``first``."""
    return service.capture("first").session.id


# ---- rename / pin / unpin / notes ---------------------------------------------


def test_rename_human_and_json(run: Run, saved: str) -> None:
    code, out, _ = run("rename", saved, "renamed")
    assert code == 0
    assert "renamed" in out
    assert saved in out

    code, out, _ = run("--json", "rename", saved, "again")
    assert code == 0
    assert json.loads(out)["name"] == "again"


def test_pin_and_unpin(run: Run, saved: str, service: SessionService) -> None:
    code, out, _ = run("pin", saved)
    assert code == 0
    assert "[pinned]" in out
    assert service.get(saved).pinned is True

    code, out, _ = run("--json", "unpin", saved)
    assert code == 0
    assert json.loads(out)["pinned"] is False
    assert service.get(saved).pinned is False


def test_notes_human_and_json(run: Run, saved: str, service: SessionService) -> None:
    code, out, _ = run("notes", saved, "remember this")
    assert code == 0
    assert saved in out
    assert service.get(saved).notes == "remember this"

    code, out, _ = run("--json", "notes", saved, "again")
    assert json.loads(out)["notes"] == "again"


def test_update_unknown_selector_is_not_found(run: Run) -> None:
    code, _, err = run("pin", "nothing")
    assert code == EXIT_NOT_FOUND
    assert err.startswith("error: ")


# ---- delete ---------------------------------------------------------------------


def test_delete_yes_moves_to_trash(run: Run, saved: str, service: SessionService) -> None:
    code, out, _ = run("delete", saved, "--yes")
    assert code == 0
    assert "trash" in out
    assert (service.store.trash_dir / f"{saved}.json").exists()
    assert service.list_sessions() == []


def test_delete_purge_json(run: Run, saved: str, service: SessionService) -> None:
    code, out, _ = run("--json", "delete", saved, "--purge", "--yes")
    data = json.loads(out)
    assert code == 0
    assert data == {"deleted": saved, "purged": True, "trash": None}
    assert not (service.store.trash_dir / f"{saved}.json").exists()
    assert service.list_sessions() == []


def test_delete_json_reports_trash_path(run: Run, saved: str) -> None:
    code, out, _ = run("--json", "delete", saved, "--yes")
    data = json.loads(out)
    assert code == 0
    assert data["purged"] is False
    assert Path(data["trash"]).exists()


def test_delete_without_yes_on_non_tty_is_usage_error(
    run: Run, saved: str, service: SessionService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    code, _, err = run("delete", saved)
    assert code == EXIT_USAGE
    assert "use --yes" in err
    assert len(service.list_sessions()) == 1


def test_delete_confirmed_on_tty(
    run: Run, saved: str, service: SessionService, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompts: list[str] = []

    def answer(prompt: str = "") -> str:
        prompts.append(prompt)
        return "y"

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", answer)
    code, _, _ = run("delete", saved)
    assert code == 0
    assert prompts == [f'Delete "first" ({saved})? [y/N] ']
    assert service.list_sessions() == []


def test_delete_declined_on_tty_keeps_session(
    run: Run, saved: str, service: SessionService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    code, _, err = run("delete", saved)
    assert code == EXIT_ERROR
    assert "cancelled" in err
    assert len(service.list_sessions()) == 1


# ---- prune ----------------------------------------------------------------------


def test_prune_human_and_json(run: Run, service: SessionService) -> None:
    ids = [service.capture(kind="auto").session.id for _ in range(3)]

    code, out, _ = run("prune", "--keep", "2")
    assert code == 0
    assert out.split() == [ids[0]]

    code, out, _ = run("--json", "prune", "--keep", "1")
    assert code == 0
    assert json.loads(out) == {"removed": [ids[1]]}


def test_prune_nothing(run: Run) -> None:
    code, out, _ = run("prune")
    assert code == 0
    assert "nothing to prune" in out


# ---- diff -----------------------------------------------------------------------


def test_diff_human_and_json(
    run: Run, service: SessionService, fake_backend: FakeWordBackend
) -> None:
    first = service.capture("one").session.id
    fake_backend.documents.append(FakeDocument(path=r"C:\Docs\c.docx"))
    fake_backend.documents.pop(0)
    second = service.capture("two").session.id

    code, out, _ = run("diff", first, second)
    assert code == 0
    assert out.splitlines() == [r"+ C:\Docs\c.docx", r"- C:\Docs\a.docx"]

    code, out, _ = run("--json", "diff", first, second)
    assert json.loads(out) == {"added": [r"C:\Docs\c.docx"], "removed": [r"C:\Docs\a.docx"]}


# ---- doctor -----------------------------------------------------------------------


def test_doctor_prints_ten_checks(run: Run) -> None:
    code, out, _ = run("doctor")
    lines = out.splitlines()
    assert len(lines) == 9
    assert code == (1 if any(line.startswith("FAIL") for line in lines) else 0)

    code, out, _ = run("--json", "doctor")
    checks = json.loads(out)
    assert [c["name"] for c in checks][:2] == ["python", "pywin32"]
    assert len(checks) == 9
    assert code == (1 if any(c["status"] == "fail" for c in checks) else 0)


# ---- shortcut --------------------------------------------------------------------


def test_shortcut_create_and_remove(
    run: Run, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        shortcut, "_write_link", lambda link, target, arguments: link.write_bytes(b"lnk")
    )
    link = isolated_home / "start-menu" / "Word Session.lnk"
    code, out, _ = run("shortcut")
    assert (code, out.strip()) == (0, f"Created {link}")
    assert link.is_file()
    code, out, _ = run("--json", "shortcut", "--remove")
    assert code == 0
    assert json.loads(out) == {"path": str(link), "exists": False}
    assert not link.exists()
    code, out, _ = run("shortcut", "--remove")
    assert (code, out.strip()) == (0, "There was no Start menu shortcut")


def test_shortcut_off_windows_fails(run: Run, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    code, _, err = run("shortcut")
    assert code == 1
    assert "only supported on Windows" in err
