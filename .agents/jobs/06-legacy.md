# Job 06 — Legacy readers and import

Depends on: 05
Plan reference: §1.2 "Data-format fragmentation", §3.4 (first-run import), §7

## Goal

Read every session file the old Python and PowerShell tools ever wrote and
import them, idempotently and without modifying the originals.

## Files

- `src/word_session/legacy.py`
- `tests/unit/test_legacy.py`
- `tests/fixtures/legacy/` (synthetic fixture files, see below)

## Legacy formats (from `legacy/python/word-session.py` and `legacy/powershell/word-session.ps1`)

| Source | Default dir | File name pattern | Top-level | Item fields | Encoding |
| --- | --- | --- | --- | --- | --- |
| Python v0 | `~/.word-session/` | `YYYYMMDDTHHMMSS word-session.json` | `{"word-session:": [ ... ]}` (note trailing colon) | `FullName`, `Line`, `Page` | UTF-8/ASCII (maybe cp1252) |
| PowerShell | `~/.word-sessions/` | `YYYYMMDDTHHMMSS-Word-session.json` | `{"sessions": [ ... ]}` or `{"sessions": { ... }}` (single doc) | `FullName`, `cursorLine`, `pageNumber` | UTF-16 LE with BOM (PS 5.1 `Out-File`); possibly UTF-8 |

## Contract

```python
class LegacyFormatError(Exception): ...

def read_session_file(path: Path) -> Session: ...
def default_legacy_dirs() -> list[Path]: ...       # [~/.word-session, ~/.word-sessions]

@dataclass
class ImportSummary:
    imported: list[str]                 # new session ids
    skipped: list[Path]                 # already imported
    errors: list[tuple[Path, str]]

def import_legacy(store: SessionStore, dirs: Iterable[Path]) -> ImportSummary: ...
```

`default_legacy_dirs` uses `Path.home()`; tests monkeypatch `Path.home`
(or `HOME`/`USERPROFILE`) to the tmp dir.

## Behaviour

- Decoding: BOM `FF FE` → `utf-16-le`; `FE FF` → `utf-16-be`;
  `EF BB BF` → `utf-8-sig`; else try `utf-8`, then `cp1252`.
- Detection: top-level `format == "word-session"` → v1 via
  `Session.model_validate` (pass-through); key `"word-session:"` → Python v0;
  key `"sessions"` → PowerShell; else `LegacyFormatError` naming the path and
  the keys found.
- Conversion to `Session`:
  - `created_at`: parsed from the leading `YYYYMMDDTHHMMSS` of the file name
    as local time made aware (`.astimezone()`), else file mtime (aware);
  - `name`: `"Imported " + created_at.strftime("%Y-%m-%d %H:%M")`;
  - `kind = "imported"`; `id` from `store.new_id(created_at, name)` (in
    `import_legacy`; `read_session_file` uses `make_session_id`);
  - documents: `path = FullName`, `location = classify_location(path)`,
    `position.page`/`line` from the item (values ≤ 0 or non-int → `None`),
    `start`/`end` `None`; first document `active = False` for all (unknown);
  - extra field on the session: `"imported_from": {"path": str(path),
    "sha256": <hex of file bytes>, "format": "python-v0" | "powershell"}`.
- `import_legacy`: for each dir that exists, each `*.json` file
  (non-recursive), sorted by name. Skip a file if any session in the store
  already has `imported_from.sha256` equal to the file's hash. Errors are
  collected, not raised. Never write to or move source files.

## Fixtures (synthetic; do not copy real user files into the repo)

Create with a small throwaway script, then commit the outputs:

1. `python_v0.json` — Python v0, two docs, ASCII.
2. `python_v0_cp1252.json` — Python v0 with a path containing `é` encoded
   cp1252.
3. `powershell_utf16.json` — PowerShell list, UTF-16 LE with BOM, CRLF.
4. `powershell_single.json` — PowerShell with `sessions` as a single object.
5. `powershell_utf8.json` — PowerShell list, UTF-8 without BOM.
6. `truncated.json` — invalid JSON.
7. `unknown.json` — valid JSON, unknown keys.
8. `v1.json` — a valid v1 file.

Name them so the timestamp rule is exercised for at least one of each
format (e.g. `20241123T101500 word-session.json`); keep a `README.md` in the
folder describing each file.

## Tests (at least)

- every fixture converts (or errors) as specified; positions and locations
  correct; `imported_from` populated;
- created_at from file name and from mtime fallback;
- `import_legacy` imports, then a second run skips everything; sources
  untouched (compare bytes and mtime); missing dirs ignored; errors
  collected.

## Optional local check (do not commit results)

If `~/.word-session` or `~/.word-sessions` exist on this machine, run
`read_session_file` over their files in a throwaway script and put the
counts of ok/failed files (no paths) in the report.

## Acceptance

README rule 7 commands.
