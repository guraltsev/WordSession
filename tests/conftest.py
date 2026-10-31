"""Shared pytest fixtures and marker handling for the Word Session tests."""

import os
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``WORD_SESSION_HOME`` at a fresh temporary directory for every test."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("WORD_SESSION_HOME", str(home))
    return home


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip tests that need real Word, a shared Word or a browser unless enabled."""
    on_windows = sys.platform == "win32"
    # Each marker is paired with the environment switch that enables it.
    rules = [
        (
            "word",
            on_windows and os.environ.get("WORD_SESSION_TEST_WORD") == "1",
            "needs WORD_SESSION_TEST_WORD=1 on Windows",
        ),
        (
            "shared_word",
            on_windows and os.environ.get("WORD_SESSION_TEST_SHARED_WORD") == "1",
            "needs WORD_SESSION_TEST_SHARED_WORD=1 on Windows",
        ),
        ("ui", os.environ.get("WORD_SESSION_TEST_UI") == "1", "needs WORD_SESSION_TEST_UI=1"),
    ]
    for marker, enabled, reason in rules:
        if enabled:
            continue
        skip = pytest.mark.skip(reason=reason)
        for item in items:
            if marker in item.keywords:
                item.add_marker(skip)
