"""Tests for the per-user Start menu shortcut (never the real Start menu)."""

import subprocess
import sys
from pathlib import Path

import pytest

from word_session import shortcut


@pytest.fixture
def written(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Path, Path, str]]:
    """Replace the PowerShell writer with one that records calls and writes a stub."""
    calls: list[tuple[Path, Path, str]] = []

    def fake_write(link: Path, target: Path, arguments: str) -> None:
        calls.append((link, target, arguments))
        link.write_bytes(b"lnk")

    monkeypatch.setattr(shortcut, "_write_link", fake_write)
    monkeypatch.setattr(sys, "platform", "win32")
    return calls


def test_path_is_under_word_session_home(isolated_home: Path) -> None:
    assert shortcut.shortcut_path() == isolated_home / "start-menu" / "Word Session.lnk"


def test_path_is_the_users_own_start_menu(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("WORD_SESSION_HOME")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    expected = tmp_path / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    assert shortcut.shortcut_path() == expected / "Word Session.lnk"


def test_create_writes_link_to_frozen_app(
    written: list[tuple[Path, Path, str]], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exe = tmp_path / "Word Session" / "word-session.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert not shortcut.exists()
    link = shortcut.create()
    assert link == shortcut.shortcut_path()
    assert shortcut.exists()
    assert written == [(link, exe.with_name("word-session.exe"), "")]


def test_create_from_source_opens_the_manager(
    written: list[tuple[Path, Path, str]], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    shortcut.create()
    assert written[0][1:] == (tmp_path / "python.exe", "-m word_session app --open")


def test_remove_deletes_and_is_harmless_when_absent(
    written: list[tuple[Path, Path, str]],
) -> None:
    assert shortcut.remove() is False
    shortcut.create()
    assert shortcut.remove() is True
    assert not shortcut.exists()


def test_create_reports_missing_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shortcut, "_write_link", lambda link, target, arguments: None)
    with pytest.raises(shortcut.ShortcutError, match="not created"):
        shortcut.create()


def test_powershell_failure_becomes_shortcut_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, "powershell", stderr="access denied")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(shortcut.ShortcutError, match="access denied"):
        shortcut._write_link(tmp_path / "x.lnk", tmp_path / "app.exe", "")


def test_not_supported_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert not shortcut.supported()
    with pytest.raises(NotImplementedError):
        shortcut.create()


@pytest.mark.skipif(sys.platform != "win32", reason="needs Windows PowerShell")
def test_real_link_is_written(isolated_home: Path) -> None:
    link = shortcut.create()
    # Every .lnk file starts with its header size (0x4C) and the shell link CLSID.
    assert link.read_bytes()[:4] == b"L\x00\x00\x00"
    assert link.parent == isolated_home / "start-menu"
