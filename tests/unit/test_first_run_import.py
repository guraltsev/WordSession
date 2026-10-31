"""Tests for the one-time automatic legacy import."""

import shutil
from pathlib import Path

import pytest

from word_session import legacy
from word_session.config import app_paths
from word_session.service import SessionService, first_run_import

FIXTURES = Path(__file__).parent.parent / "fixtures" / "legacy"


def _legacy_dir(tmp_path: Path, *names: str) -> Path:
    """Copy the named legacy fixtures into a fresh folder and return it."""
    folder = tmp_path / "old"
    folder.mkdir()
    for name in names:
        shutil.copy(FIXTURES / name, folder)
    return folder


def test_runs_once_and_writes_marker(
    service: SessionService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _legacy_dir(tmp_path, "20241123T101500 word-session.json", "v1.json")
    monkeypatch.setattr(legacy, "default_legacy_dirs", lambda: [folder])
    paths = app_paths()

    summary = first_run_import(service, paths)

    assert summary is not None
    assert len(summary.imported) == 2
    marker = paths.data_dir / ".legacy-imported"
    assert marker.exists()
    assert "imported=2" in marker.read_text(encoding="utf-8")
    assert len(service.list_sessions()) == 2

    assert first_run_import(service, paths) is None
    assert len(service.list_sessions()) == 2


def test_errors_still_write_marker(
    service: SessionService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _legacy_dir(tmp_path, "unknown.json", "truncated.json")
    monkeypatch.setattr(legacy, "default_legacy_dirs", lambda: [folder])
    paths = app_paths()

    summary = first_run_import(service, paths)

    assert summary is not None
    assert summary.imported == []
    assert len(summary.errors) == 2
    assert (paths.data_dir / ".legacy-imported").exists()
    assert first_run_import(service, paths) is None


def test_existing_marker_skips_import(
    service: SessionService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _legacy_dir(tmp_path, "v1.json")
    monkeypatch.setattr(legacy, "default_legacy_dirs", lambda: [folder])
    paths = app_paths()
    (paths.data_dir / ".legacy-imported").write_text("done", encoding="utf-8")

    assert first_run_import(service, paths) is None
    assert service.list_sessions() == []
