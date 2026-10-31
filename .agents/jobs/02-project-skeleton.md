# Job 02 — Project skeleton

Depends on: 01
Plan reference: §3.2, §5, §4 (tooling)
Decisions: D4 (Python version)

## Goal

Create an installable, `uv`-managed package `word_session` with linting,
type checking and a test harness, so every later job adds code to a working
project.

## Files

- `pyproject.toml`, `uv.lock` (generated), `.python-version`
- `src/word_session/__init__.py`, `src/word_session/__main__.py`,
  `src/word_session/cli.py` (stub), `src/word_session/py.typed`
- `tests/__init__.py` (empty), `tests/conftest.py`, `tests/unit/test_smoke.py`

## Do

1. `uv init` is **not** used; write `pyproject.toml` by hand:
   - `[project]` name `word-session`, `version = "0.1.0"`, description
     "Save and restore Microsoft Word sessions", `requires-python` per D4,
     no `readme` key.
   - dependencies (runtime): `pydantic>=2.8`, `platformdirs>=4`,
     `tomli-w>=1`, `pywin32>=308; sys_platform == 'win32'`. (Web/tray deps
     are added by their jobs.)
   - `[project.scripts]` `word-session = "word_session.cli:main"`.
   - `[project.gui-scripts]` `word-session-app = "word_session.cli:app_main"`.
   - build backend `hatchling`, `[tool.hatch.build.targets.wheel]
     packages = ["src/word_session"]`.
   - `[dependency-groups] dev = ["pytest>=8", "pytest-cov>=5", "ruff>=0.6",
     "pyright>=1.1.380"]`.
   - `[tool.ruff]` `line-length = 100`, `target-version = "py313"`,
     `src = ["src", "tests"]`; `[tool.ruff.lint] select = ["E","F","W","I",
     "UP","B","SIM","PTH","RUF"]`, `ignore = ["E501"]`.
   - `[tool.pyright]` `include = ["src", "tests"]`, `pythonVersion = "3.13"`,
     `typeCheckingMode = "standard"`, `reportMissingModuleSource = false`.
   - `[tool.pytest.ini_options]` `testpaths = ["tests"]`,
     `addopts = "-ra --strict-markers"`, markers:
     `word: drives a real Microsoft Word (needs WORD_SESSION_TEST_WORD=1)`,
     `shared_word: attaches to the user's running Word (needs WORD_SESSION_TEST_SHARED_WORD=1)`,
     `ui: browser UI tests (needs Playwright browsers)`.
2. `.python-version` containing `3.13`. Run `uv python install 3.13` if
   needed, then `uv sync`.
3. `src/word_session/__init__.py`: module docstring (per
   `docs/docstring_schema.md`) and `__version__` read via
   `importlib.metadata.version("word-session")` with fallback `"0.0.0"` on
   `PackageNotFoundError`.
4. `src/word_session/__main__.py`: `raise SystemExit(main())` importing
   `main` from `word_session.cli`.
5. `src/word_session/cli.py` (temporary stub, replaced in job 12):
   `main(argv: list[str] | None = None) -> int` with argparse supporting only
   `--version` (prints `word-session <version>`, returns 0); with no args
   prints help and returns 2. `app_main() -> None` raises
   `SystemExit(main(["app"]))` — for now that returns 2; fine.
6. `tests/conftest.py`:
   - fixture `isolated_home(tmp_path, monkeypatch) -> Path`: sets
     `WORD_SESSION_HOME` to `tmp_path / "home"` (created) and returns it.
     **autouse=True**, so no test can accidentally hit the real home.
   - `pytest_collection_modifyitems`: skip items marked `word` unless
     `os.environ.get("WORD_SESSION_TEST_WORD") == "1"` and
     `sys.platform == "win32"`; skip items marked `shared_word` unless
     `WORD_SESSION_TEST_SHARED_WORD == "1"` on win32; skip items marked `ui`
     unless `WORD_SESSION_TEST_UI == "1"`.
7. `tests/unit/test_smoke.py`: `--version` returns 0 and prints the version;
   no args returns 2; `python -m word_session --version` works via
   `subprocess.run([sys.executable, "-m", "word_session", "--version"])`;
   `isolated_home` sets the env var.

## Do not

- No other modules yet. No web/tray dependencies.

## Acceptance

```text
uv sync
uv run word-session --version
uv run python -m word_session --version
uv run ruff format --check . && uv run ruff check . && uv run pyright && uv run pytest
```

`legacy/` must be excluded from ruff and pyright (add `extend-exclude =
["legacy"]` to ruff and `exclude = ["legacy"]` to pyright) since it is not
maintained code.

## Report

Standard report.
