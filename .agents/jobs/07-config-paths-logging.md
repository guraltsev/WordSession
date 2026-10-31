# Job 07 — Config, paths, logging

Depends on: 02
Plan reference: §3.4, §3.10
Decisions: D1 (sessions directory)

## Goal

Give the app one place that decides where things live, what the user's
settings are, and how logs are written — with a single environment variable
that redirects everything for tests.

## Files

- `src/word_session/config.py`
- `src/word_session/logging_setup.py`
- `tests/unit/test_config.py`, `tests/unit/test_logging_setup.py`

## Contract

```python
@dataclass(frozen=True)
class AppPaths:
    data_dir: Path        # parent of sessions; also holds config.toml
    sessions_dir: Path
    config_file: Path
    log_dir: Path
    instance_file: Path   # instance.json

def app_paths() -> AppPaths: ...

class AutosaveSettings(BaseModel):
    enabled: bool = True
    interval_minutes: int = Field(10, ge=1, le=1440)
    keep: int = Field(20, ge=0, le=10000)
    only_on_change: bool = True

class RestoreSettings(BaseModel):
    start_word: bool = True
    restore_position: bool = True
    open_timeout_s: float = Field(60, gt=0, le=3600)

class UiSettings(BaseModel):
    start_at_login: bool = False

class Settings(BaseModel):          # model_config extra="forbid"
    sessions_dir: Path | None = None   # None → AppPaths.sessions_dir
    autosave: AutosaveSettings = Field(default_factory=AutosaveSettings)
    restore: RestoreSettings = Field(default_factory=RestoreSettings)
    ui: UiSettings = Field(default_factory=UiSettings)

class ConfigError(Exception): ...

def load_settings(path: Path | None = None) -> Settings: ...
def save_settings(settings: Settings, path: Path | None = None) -> None: ...
def resolve_sessions_dir(settings: Settings, paths: AppPaths) -> Path: ...

def configure_logging(log_dir: Path, *, console_level: int | None) -> None: ...
```

## Behaviour

- `app_paths()`:
  - If env `WORD_SESSION_HOME` is set (call it `home`): everything lives
    under it — `data_dir = home`, `sessions_dir = home/"sessions"`,
    `config_file = home/"config.toml"`,
    `log_dir = home/"logs"`, `instance_file = home/"instance.json"`.
  - Else (D1): `data_dir = Path(platformdirs.user_data_dir("word-session",
    appauthor=False, roaming=True))`, `sessions_dir = data_dir/"sessions"`,
    `config_file = data_dir/"config.toml"`,
    `log_dir = Path(platformdirs.user_log_dir("word-session", appauthor=False))`,
    `instance_file = Path(platformdirs.user_state_dir("word-session", appauthor=False))/"instance.json"`
    (on Windows this lands under `%LOCALAPPDATA%`).
  - Creates nothing.
- `load_settings(path)`: default path `app_paths().config_file`. Missing file
  → `Settings()`. TOML parse error or validation error → `ConfigError` whose
  message includes the path and the offending key/line.
- `save_settings`: TOML via `tomli_w`, atomic (temp + `os.replace`), creates
  the parent dir; omit `sessions_dir` when `None`.
- `resolve_sessions_dir`: `settings.sessions_dir` expanded (`~`) if set,
  else `paths.sessions_dir`.
- `configure_logging`: idempotent (calling twice must not duplicate
  handlers — tag handlers with an attribute and remove previous ones). Root
  logger level `DEBUG`. File handler: `RotatingFileHandler(log_dir /
  "word-session.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")`,
  level `DEBUG`, format `%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s`.
  Console handler (stderr) only if `console_level` is not `None`, format
  `%(levelname)s: %(message)s`. Creates `log_dir`. If the log dir cannot be
  created, fall back to console-only and emit one warning — never crash.

## Tests (at least)

- `WORD_SESSION_HOME` redirection (the autouse fixture already sets it —
  assert the values), and the platformdirs branch with the env var removed
  (only assert path suffixes; do not create anything);
- defaults when no file; round-trip save/load; invalid TOML and invalid
  values produce `ConfigError` mentioning the key; unknown key rejected;
- `resolve_sessions_dir` both branches and `~` expansion;
- logging idempotence, file created and written, console handler toggle,
  unwritable log dir fallback (monkeypatch `Path.mkdir` to raise).

## Acceptance

README rule 7 commands.
