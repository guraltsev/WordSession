"""Tests for the core command-line commands."""

import json
import logging
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from word_session import __version__
from word_session.cli import (
    EXIT_ERROR,
    EXIT_NOT_FOUND,
    EXIT_NOT_RESPONDING,
    EXIT_PARTIAL_RESTORE,
    EXIT_USAGE,
    EXIT_WORD_UNAVAILABLE,
    main,
)
from word_session.config import ConfigError
from word_session.service import SessionService
from word_session.word.backend import WordNotResponding
from word_session.word.fake import FakeWordBackend

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
    # The fixture's worker is stopped by its own teardown, so ``close`` is a no-op here.
    service.close = lambda: None  # type: ignore[method-assign]

    def _run(*argv: str) -> tuple[int, str, str]:
        capsys.readouterr()
        code = main(list(argv), service_factory=lambda args: service)
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


# ---- save / current / list / show ----------------------------------------------


def test_save_human_and_json(run: Run) -> None:
    code, out, _ = run("save", "--name", "mine")
    assert code == 0
    assert 'Saved "mine" (2 documents)' in out

    code, out, _ = run("--json", "save")
    data = json.loads(out)
    assert code == 0
    assert len(data["session"]["documents"]) == 2
    assert Path(data["path"]).exists()
    assert data["warnings"] == []


def test_save_warnings_go_to_stderr(run: Run, fake_backend: FakeWordBackend) -> None:
    fake_backend.documents[0].saved = False
    code, out, err = run("save")
    assert code == 0
    assert "warning: " in err
    assert "warning: " not in out


def test_save_with_no_documents_is_not_an_error(run: Run, fake_backend: FakeWordBackend) -> None:
    fake_backend.documents.clear()
    code, out, _ = run("save")
    assert code == 0
    assert "nothing saved" in out
    code, out, _ = run("--json", "save")
    assert json.loads(out)["path"] is None


def test_current_human_and_json(run: Run) -> None:
    code, out, _ = run("current")
    assert code == 0
    assert out.count("\n") == 2
    assert "* C:\\Docs\\b.docx" in out
    code, out, _ = run("--json", "current")
    assert [d["path"] for d in json.loads(out)] == [r"C:\Docs\a.docx", r"C:\Docs\b.docx"]


def test_list_orders_filters_and_limits(run: Run) -> None:
    run("save", "--name", "first")
    run("save", "--name", "second")
    code, out, _ = run("list")
    assert code == 0
    lines = out.splitlines()
    assert "second" in lines[0] and "first" in lines[1]
    assert "manual" in lines[0]

    _, out, _ = run("--json", "list", "--limit", "1")
    assert [s["name"] for s in json.loads(out)] == ["second"]
    _, out, _ = run("--json", "list", "--kind", "auto")
    assert json.loads(out) == []


def test_list_marks_pinned(run: Run, service: SessionService) -> None:
    run("save", "--name", "keep")
    service.update("latest", pinned=True)
    _, out, _ = run("list")
    assert "[pinned]" in out


def test_show_human_and_json(run: Run) -> None:
    run("save", "--name", "shown")
    code, out, _ = run("show", "latest")
    assert code == 0
    assert "shown" in out and "testhost" in out and r"C:\Docs\a.docx" in out
    assert "exists" in out or "MISSING" in out
    code, out, _ = run("--json", "show", "shown")
    assert json.loads(out)["name"] == "shown"


# ---- restore -----------------------------------------------------------------


def test_restore_defaults_to_latest(run: Run) -> None:
    run("save", "--name", "s")
    code, out, _ = run("restore")
    assert code == 0
    assert "2 already_open" in out


def test_load_is_an_alias(run: Run) -> None:
    run("save")
    code, out, _ = run("--json", "load", "latest")
    assert code == 0
    assert json.loads(out)["dry_run"] is False


def test_restore_dry_run_json_is_report(run: Run) -> None:
    run("save")
    code, out, _ = run("--json", "restore", "--dry-run")
    data = json.loads(out)
    assert code == 0
    assert data["dry_run"] is True
    assert {r["status"] for r in data["results"]} == {"skipped"}


def test_restore_only_filters(run: Run) -> None:
    run("save")
    _, out, _ = run("--json", "restore", "--dry-run", "--only", "a.docx")
    assert [r["path"] for r in json.loads(out)["results"]] == [r"C:\Docs\a.docx"]


def test_restore_no_start_with_stopped_word(run: Run, fake_backend: FakeWordBackend) -> None:
    run("save")
    fake_backend.running = False
    code, _, err = run("restore", "--no-start")
    assert code == EXIT_WORD_UNAVAILABLE
    assert "Word is not running" in err
    assert "omit --no-start" in err
    code, out, _ = run("--json", "restore", "--no-start")
    assert code == EXIT_WORD_UNAVAILABLE
    assert json.loads(out)["error"]["type"] == "WordUnavailable"


def test_restore_position_flag(run: Run, fake_backend: FakeWordBackend) -> None:
    run("save")
    fake_backend.calls.clear()
    run("restore")
    assert "restore_position" in fake_backend.calls
    fake_backend.calls.clear()
    run("restore", "--no-position")
    assert "restore_position" not in fake_backend.calls


def test_partial_restore_exit_code(run: Run, fake_backend: FakeWordBackend) -> None:
    fake_backend.documents[0].path = r"C:\Docs\missing.docx"
    run("save")
    code, out, _ = run("restore")
    assert code == EXIT_PARTIAL_RESTORE
    assert "missing" in out
    code, out, _ = run("--json", "restore")
    assert code == EXIT_PARTIAL_RESTORE
    assert "missing" in {r["status"] for r in json.loads(out)["results"]}


# ---- errors ------------------------------------------------------------------


def test_session_not_found(run: Run) -> None:
    code, _, err = run("show", "nothing")
    assert code == EXIT_NOT_FOUND
    assert err.startswith("error: ")
    code, out, _ = run("--json", "show", "nothing")
    assert code == EXIT_NOT_FOUND
    assert json.loads(out)["error"]["type"] == "SessionNotFound"


def test_ambiguous_selector_lists_candidates(run: Run) -> None:
    run("save", "--name", "same")
    run("save", "--name", "same")
    code, _, err = run("show", "same")
    assert code == EXIT_NOT_FOUND
    assert err.count("candidate:") == 2


def test_word_not_running_for_save(run: Run, fake_backend: FakeWordBackend) -> None:
    fake_backend.running = False
    code, _, err = run("save")
    assert code == EXIT_WORD_UNAVAILABLE
    assert "Word is not running" in err


def test_word_not_responding(run: Run, monkeypatch: pytest.MonkeyPatch) -> None:
    def hang(self: FakeWordBackend) -> list:
        raise WordNotResponding("busy")

    monkeypatch.setattr(FakeWordBackend, "list_documents", hang)
    code, _, err = run("current")
    assert code == EXIT_NOT_RESPONDING
    assert "busy" in err


def test_config_error_is_exit_one(capsys: pytest.CaptureFixture[str]) -> None:
    def factory(args: object) -> SessionService:
        raise ConfigError("bad config")

    code = main(["list"], service_factory=factory)
    assert code == EXIT_ERROR
    assert "error: bad config" in capsys.readouterr().err


def test_unexpected_error_points_to_log(capsys: pytest.CaptureFixture[str]) -> None:
    def factory(args: object) -> SessionService:
        raise RuntimeError("boom")

    code = main(["--json", "list"], service_factory=factory)
    assert code == EXIT_ERROR
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "RuntimeError"

    main(["list"], service_factory=factory)
    err = capsys.readouterr().err
    assert "unexpected error, see " in err
    assert "boom" not in err

    main(["-v", "list"], service_factory=factory)
    assert "Traceback" in capsys.readouterr().err


# ---- global options ------------------------------------------------------------


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"word-session {__version__}"


def test_no_command_and_bad_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == EXIT_USAGE
    assert "usage" in capsys.readouterr().out.lower()
    assert main(["bogus"]) == EXIT_USAGE
    assert main(["list", "--kind", "weird"]) == EXIT_USAGE


def test_quiet_suppresses_output(run: Run) -> None:
    code, out, err = run("-q", "save")
    assert code == 0
    assert out == "" and err == ""
    code, _, err = run("-q", "show", "nothing")
    assert code == EXIT_NOT_FOUND
    assert "error:" in err


def test_sessions_dir_override_with_demo(
    isolated_home: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    target = tmp_path / "elsewhere"
    assert main(["--demo", "--sessions-dir", str(target), "save", "--name", "d"]) == 0
    capsys.readouterr()
    assert len(list(target.glob("*.json"))) == 1
    assert not (isolated_home / "sessions").exists()
    assert main(["--demo", "--sessions-dir", str(target), "--json", "list"]) == 0
    assert [s["name"] for s in json.loads(capsys.readouterr().out)] == ["d"]


def test_demo_without_override_uses_home(
    isolated_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--demo", "save"]) == 0
    assert list((isolated_home / "sessions").glob("*.json"))
