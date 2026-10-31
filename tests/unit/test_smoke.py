"""Smoke tests for the package skeleton."""

import os
import subprocess
import sys

import pytest

from word_session import __version__
from word_session.cli import main


def test_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"word-session {__version__}"


def test_no_arguments_returns_two(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "usage" in capsys.readouterr().out.lower()


def test_module_entry_point_prints_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "word_session", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == f"word-session {__version__}"


def test_isolated_home_sets_environment(isolated_home) -> None:
    assert os.environ["WORD_SESSION_HOME"] == str(isolated_home)
    assert isolated_home.is_dir()
