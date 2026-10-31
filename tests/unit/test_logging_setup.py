"""Tests for logging configuration."""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from word_session.logging_setup import configure_logging


@pytest.fixture(autouse=True)
def restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for handler in list(root.handlers):
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)


def _tagged() -> list[logging.Handler]:
    return [h for h in logging.getLogger().handlers if getattr(h, "_word_session_handler", False)]


def test_idempotent(tmp_path: Path) -> None:
    configure_logging(tmp_path / "logs", console_level=logging.INFO)
    configure_logging(tmp_path / "logs", console_level=logging.INFO)
    assert len(_tagged()) == 2


def test_file_created_and_written(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    configure_logging(log_dir, console_level=None)
    logging.getLogger("word_session.test").debug("hello file")
    for handler in _tagged():
        handler.flush()
    text = (log_dir / "word-session.log").read_text(encoding="utf-8")
    assert "hello file" in text
    assert "DEBUG" in text
    assert logging.getLogger().level == logging.DEBUG


def test_console_toggle(tmp_path: Path) -> None:
    configure_logging(tmp_path / "logs", console_level=None)
    assert len(_tagged()) == 1
    configure_logging(tmp_path / "logs", console_level=logging.WARNING)
    assert len(_tagged()) == 2
    configure_logging(tmp_path / "logs", console_level=None)
    assert len(_tagged()) == 1


def test_unwritable_log_dir_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "mkdir", broken_mkdir)
    configure_logging(tmp_path / "logs", console_level=logging.INFO)
    handlers = _tagged()
    assert len(handlers) == 1
    assert not isinstance(handlers[0], logging.FileHandler)
