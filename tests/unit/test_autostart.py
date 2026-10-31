"""Tests for start-at-login registration using a fake ``winreg``."""

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from word_session import autostart

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class FakeKey:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def __enter__(self) -> "FakeKey":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def make_winreg(store: dict[str, str], *, key_exists: bool = True) -> Any:
    state: dict[str, Any] = {"exists": key_exists, "opened": []}

    def open_key(root: object, sub: str, reserved: int, access: int) -> FakeKey:
        state["opened"].append((root, sub))
        if not state["exists"]:
            raise FileNotFoundError(sub)
        return FakeKey(store)

    def create_key(root: object, sub: str) -> FakeKey:
        state["opened"].append((root, sub))
        state["exists"] = True
        return FakeKey(store)

    def query(key: FakeKey, name: str) -> tuple[str, int]:
        if name not in key.values:
            raise FileNotFoundError(name)
        return key.values[name], 1

    def set_value(key: FakeKey, name: str, reserved: int, kind: int, value: str) -> None:
        key.values[name] = value

    def delete(key: FakeKey, name: str) -> None:
        if name not in key.values:
            raise FileNotFoundError(name)
        del key.values[name]

    return SimpleNamespace(
        HKEY_CURRENT_USER="HKCU",
        KEY_READ=1,
        KEY_SET_VALUE=2,
        REG_SZ=1,
        OpenKey=open_key,
        CreateKey=create_key,
        QueryValueEx=query,
        SetValueEx=set_value,
        DeleteValue=delete,
        state=state,
    )


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    store: dict[str, str] = {}
    fake = make_winreg(store)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(autostart, "_winreg", lambda: fake)
    return store


def test_enable_disable_round_trip(registry: dict[str, str]) -> None:
    assert not autostart.is_enabled()
    autostart.enable('"C:\\app.exe"')
    assert registry == {"WordSession": '"C:\\app.exe"'}
    assert autostart.is_enabled()
    autostart.disable()
    assert registry == {}
    assert not autostart.is_enabled()
    autostart.disable()  # an absent value is fine


def test_missing_run_key_is_not_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = make_winreg({}, key_exists=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(autostart, "_winreg", lambda: fake)
    assert not autostart.is_enabled()
    autostart.disable()


def test_uses_current_user_run_key(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = make_winreg({})
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(autostart, "_winreg", lambda: fake)
    autostart.enable("cmd")
    assert fake.state["opened"] == [("HKCU", RUN_KEY)]


def test_non_windows_behaviour(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert not autostart.is_enabled()
    with pytest.raises(NotImplementedError):
        autostart.enable("x")
    with pytest.raises(NotImplementedError):
        autostart.disable()


def test_app_command_frozen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    exe = tmp_path / "Word Session" / "word-session-cli.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert autostart.app_command() == f'"{exe.with_name("word-session.exe")}"'


def test_app_command_from_source(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    python = tmp_path / "python.exe"
    monkeypatch.setattr(sys, "executable", str(python))
    assert autostart.app_command() == f'"{python}" -m word_session app'
    (tmp_path / "pythonw.exe").write_bytes(b"")
    assert autostart.app_command() == f'"{tmp_path / "pythonw.exe"}" -m word_session app'


def test_app_launcher_open_manager(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    assert autostart.app_launcher(open_manager=True) == (
        tmp_path / "python.exe",
        "-m word_session app --open",
    )
    # The frozen windowed launcher always opens the manager by itself.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert autostart.app_launcher(open_manager=True) == (tmp_path / "word-session.exe", "")
