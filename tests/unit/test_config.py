"""Tests for application paths and settings."""

from pathlib import Path

import pytest

from word_session.config import (
    AppPaths,
    ConfigError,
    Settings,
    app_paths,
    load_settings,
    resolve_sessions_dir,
    save_settings,
)


def test_app_paths_follow_home_variable(isolated_home: Path) -> None:
    paths = app_paths()
    assert paths.data_dir == isolated_home
    assert paths.sessions_dir == isolated_home / "sessions"
    assert paths.config_file == isolated_home / "config.toml"
    assert paths.log_dir == isolated_home / "logs"
    assert paths.instance_file == isolated_home / "instance.json"
    assert not paths.sessions_dir.exists()


def test_app_paths_platformdirs_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORD_SESSION_HOME")
    paths = app_paths()
    assert paths.data_dir.name == "word-session"
    assert paths.sessions_dir == paths.data_dir / "sessions"
    assert paths.config_file == paths.data_dir / "config.toml"
    assert paths.instance_file.name == "instance.json"
    assert paths.instance_file.parent.name == "word-session"
    assert "word-session" in paths.log_dir.parts


def test_defaults_when_no_file(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "missing.toml")
    assert settings == Settings()
    assert settings.autosave.interval_minutes == 10
    assert settings.restore.open_timeout_s == 60


def test_default_path_is_config_file(isolated_home: Path) -> None:
    save_settings(Settings())
    assert (isolated_home / "config.toml").is_file()
    assert load_settings() == Settings()


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "config.toml"
    settings = Settings.model_validate(
        {
            "sessions_dir": str(tmp_path / "s"),
            "autosave": {"enabled": False, "interval_minutes": 5, "keep": 3},
            "restore": {"open_timeout_s": 12.5},
            "ui": {"start_at_login": True},
        }
    )
    save_settings(settings, path)
    assert load_settings(path) == settings
    assert not list(path.parent.glob("*.tmp"))


def test_none_sessions_dir_is_omitted(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    save_settings(Settings(), path)
    assert "sessions_dir" not in path.read_text(encoding="utf-8")
    assert load_settings(path).sessions_dir is None


def test_invalid_toml_mentions_path(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("autosave = [\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"config.toml"):
        load_settings(path)


def test_invalid_value_mentions_key(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[autosave]\ninterval_minutes = 0\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"autosave\.interval_minutes"):
        load_settings(path)


def test_unknown_key_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("bogus = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="bogus"):
        load_settings(path)


def test_resolve_sessions_dir_default(isolated_home: Path) -> None:
    paths = app_paths()
    assert resolve_sessions_dir(Settings(), paths) == isolated_home / "sessions"


def test_resolve_sessions_dir_override_expands_home(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path, tmp_path / "s", tmp_path / "c", tmp_path / "l", tmp_path / "i")
    resolved = resolve_sessions_dir(Settings(sessions_dir=Path("~/ws-sessions")), paths)
    assert resolved == Path("~/ws-sessions").expanduser()
    assert "~" not in str(resolved)
    explicit = resolve_sessions_dir(Settings(sessions_dir=tmp_path / "x"), paths)
    assert explicit == tmp_path / "x"
