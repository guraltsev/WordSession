"""Fixtures shared by the command-line tests."""

from pathlib import Path

import pytest

from word_session import legacy


@pytest.fixture(autouse=True)
def _no_real_legacy_dirs(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Make the first-run import look only in an empty folder inside the test home."""
    folder = isolated_home / "no-legacy"
    monkeypatch.setattr(legacy, "default_legacy_dirs", lambda: [folder])
    return folder
