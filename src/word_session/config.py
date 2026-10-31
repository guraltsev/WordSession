"""Locate application directories and load or save the user's settings.

Call ``app_paths()`` to learn where sessions, configuration, logs and the
instance file live, ``load_settings()`` to read ``config.toml`` and
``save_settings(...)`` to write it. Setting the ``WORD_SESSION_HOME``
environment variable redirects every location under one directory, which is how
tests stay away from the user's real data. Path lookup creates nothing; saving
settings creates the parent directory and replaces the file atomically.
"""

import os
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

import platformdirs
import tomli_w
from pydantic import BaseModel, ConfigDict, Field, ValidationError


@dataclass(frozen=True)
class AppPaths:
    """Hold the filesystem locations used by the application."""

    data_dir: Path  # parent of sessions; also holds config.toml
    sessions_dir: Path
    config_file: Path
    log_dir: Path
    instance_file: Path  # instance.json


class AutosaveSettings(BaseModel):
    """Describe how automatic session saving behaves."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    interval_minutes: int = Field(default=10, ge=1, le=1440)
    keep: int = Field(default=20, ge=0, le=10000)
    only_on_change: bool = True


class RestoreSettings(BaseModel):
    """Describe how sessions are restored into Word."""

    model_config = ConfigDict(extra="forbid")

    start_word: bool = True
    restore_position: bool = True
    open_timeout_s: float = Field(default=60, gt=0, le=3600)


class UiSettings(BaseModel):
    """Describe user-interface preferences."""

    model_config = ConfigDict(extra="forbid")

    start_at_login: bool = False


class Settings(BaseModel):
    """Hold every user setting stored in ``config.toml``."""

    model_config = ConfigDict(extra="forbid")

    sessions_dir: Path | None = None  # None means AppPaths.sessions_dir
    autosave: AutosaveSettings = Field(default_factory=lambda: AutosaveSettings())
    restore: RestoreSettings = Field(default_factory=lambda: RestoreSettings())
    ui: UiSettings = Field(default_factory=lambda: UiSettings())


class ConfigError(Exception):
    """Signal that the configuration file cannot be read or is invalid."""


def app_paths() -> AppPaths:
    """Return the application directories without creating any of them.

    Returns
    -------
    AppPaths
        Locations under ``WORD_SESSION_HOME`` when that variable is set,
        otherwise the per-user platform directories.
    """
    # A test or portable setup redirects everything under one directory.
    home_env = os.environ.get("WORD_SESSION_HOME")
    if home_env:
        home = Path(home_env)
        return AppPaths(
            data_dir=home,
            sessions_dir=home / "sessions",
            config_file=home / "config.toml",
            log_dir=home / "logs",
            instance_file=home / "instance.json",
        )

    # Normal use: roaming data for sessions and config, local dirs for the rest.
    data_dir = Path(platformdirs.user_data_dir("word-session", appauthor=False, roaming=True))
    state_dir = Path(platformdirs.user_state_dir("word-session", appauthor=False))
    return AppPaths(
        data_dir=data_dir,
        sessions_dir=data_dir / "sessions",
        config_file=data_dir / "config.toml",
        log_dir=Path(platformdirs.user_log_dir("word-session", appauthor=False)),
        instance_file=state_dir / "instance.json",
    )


def load_settings(path: Path | None = None) -> Settings:
    """Read settings from a TOML file, using defaults when it does not exist.

    Parameters
    ----------
    path : Path or None
        File to read; defaults to ``app_paths().config_file``.

    Returns
    -------
    Settings
        The validated settings.

    Raises
    ------
    ConfigError
        If the file is not valid TOML or holds invalid or unknown keys. The
        message names the file and the offending line or key.
    """
    if path is None:
        path = app_paths().config_file

    # A missing file is the normal first-run state.
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Settings()
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"Cannot read config file {path}: {exc}") from exc

    # tomllib reports the line and column of syntax errors in its message.
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc

    # Name each failing key by its dotted location.
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in err['loc']) or '(root)'}: {err['msg']}"
            for err in exc.errors()
        )
        raise ConfigError(f"Invalid settings in {path}: {problems}") from exc


def save_settings(settings: Settings, path: Path | None = None) -> None:
    """Write settings to a TOML file atomically.

    Parameters
    ----------
    settings : Settings
        Settings to store; ``sessions_dir`` is omitted when it is ``None``.
    path : Path or None
        Destination; defaults to ``app_paths().config_file``.
    """
    if path is None:
        path = app_paths().config_file

    # TOML has no null, so unset values are left out entirely.
    data = settings.model_dump(mode="json", exclude_none=True)

    # Write to a temp file beside the target, then swap it in, so readers never
    # see a half-written file.
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            tomli_w.dump(data, handle)
        Path(tmp_name).replace(path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def resolve_sessions_dir(settings: Settings, paths: AppPaths) -> Path:
    """Return the sessions directory chosen by the settings or the defaults.

    Parameters
    ----------
    settings : Settings
        User settings; ``sessions_dir`` overrides the default when set.
    paths : AppPaths
        Default locations.

    Returns
    -------
    Path
        The user-expanded configured directory, else ``paths.sessions_dir``.
    """
    if settings.sessions_dir is not None:
        return settings.sessions_dir.expanduser()
    return paths.sessions_dir
