"""Tests for the doctor diagnostics, using injected probes."""

import sys

import pytest

from word_session.config import app_paths
from word_session.doctor import Check, run_checks
from word_session.service import SessionService
from word_session.word.fake import FakeWordBackend

NAMES = [
    "python",
    "pywin32",
    "word-installed",
    "word-running",
    "word-process",
    "elevated",
    "sessions-dir",
    "config",
    "log",
]


def _checks(
    service: SessionService,
    *,
    tasklist: str = "",
    admin: bool = False,
    registered: bool = True,
) -> dict[str, Check]:
    """Run the checks with fixed probes and index them by name."""
    results = run_checks(
        service,
        app_paths(),
        tasklist=lambda: tasklist,
        is_admin=lambda: admin,
        word_registered=lambda: registered,
    )
    assert [c.name for c in results] == NAMES
    return {c.name: c for c in results}


def test_all_ten_checks_in_order_when_healthy(service: SessionService) -> None:
    checks = _checks(service, tasklist="WINWORD.EXE  1234 Console 1  50,000 K")
    assert checks["python"].status == "ok"
    assert checks["word-installed"].status == "ok"
    assert checks["word-running"].status == "ok"
    assert checks["word-process"].status == "ok"
    assert checks["elevated"].status == "ok"
    assert checks["sessions-dir"].status == "ok"
    assert checks["config"].status == "ok"
    assert checks["log"].detail.endswith("word-session.log")


def test_pywin32_status_matches_platform(service: SessionService) -> None:
    check = _checks(service)["pywin32"]
    if check.status != "ok":
        assert check.status == ("fail" if sys.platform == "win32" else "warn")


def test_word_not_installed(service: SessionService) -> None:
    check = _checks(service, registered=False)["word-installed"]
    assert check.status == ("fail" if sys.platform == "win32" else "warn")


def test_word_not_running_without_process(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    fake_backend.running = False
    checks = _checks(service, tasklist="INFO: No tasks are running which match the criteria.")
    assert checks["word-running"].status == "warn"
    assert checks["word-process"].status == "ok"


def test_process_exists_but_not_reachable_fails(
    service: SessionService, fake_backend: FakeWordBackend
) -> None:
    fake_backend.running = False
    checks = _checks(service, tasklist="WINWORD.EXE 99 Console 1 10 K")
    assert checks["word-running"].status == "warn"
    assert checks["word-process"].status == "fail"
    assert "different privilege levels" in checks["word-process"].detail


def test_elevated_warns(service: SessionService) -> None:
    assert _checks(service, admin=True)["elevated"].status == "warn"


def test_invalid_session_file_warns(service: SessionService) -> None:
    service.capture("ok")
    (service.store.root / "broken.json").write_text("{not json", encoding="utf-8")
    check = _checks(service)["sessions-dir"]
    assert check.status == "warn"
    assert "1 sessions, 1 invalid" in check.detail


def test_bad_config_fails_without_stopping_others(service: SessionService) -> None:
    app_paths().config_file.write_text("this is = = not toml", encoding="utf-8")
    checks = _checks(service)
    assert checks["config"].status == "fail"


def test_exception_in_check_becomes_fail(
    service: SessionService, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> list[object]:
        raise RuntimeError("store exploded")

    monkeypatch.setattr(service.store, "list", boom)
    checks = _checks(service)
    assert checks["sessions-dir"].status == "fail"
    assert checks["sessions-dir"].detail == "store exploded"
