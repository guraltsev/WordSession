# Job 04 — Data model

Depends on: 02
Plan reference: §3.3, §3.6
Decisions: D2 (pydantic v2)

## Goal

Define the pure, I/O-free data types every other layer exchanges: sessions,
documents, positions and restore reports, plus the session file format v1.

## Files

- `src/word_session/model.py`
- `tests/unit/test_model.py`

## Contract (exact names; later jobs depend on them)

```python
Location = Literal["local", "unc", "url", "unsaved"]
SessionKind = Literal["manual", "auto", "imported"]
RestoreStatus = Literal["opened", "already_open", "missing", "locked", "failed", "skipped"]

class Position(BaseModel):          # all optional
    start: int | None = None        # Selection.Start (character offset)
    end: int | None = None
    page: int | None = None         # 1-based; None if Word reported <= 0
    line: int | None = None         # 1-based line on that page

class WindowState(BaseModel):
    state: Literal["normal", "maximized", "minimized"] | None = None

class DocumentState(BaseModel):     # model_config: extra="allow"
    path: str
    location: Location
    position: Position = Field(default_factory=Position)
    active: bool = False
    read_only: bool = False
    had_unsaved_changes: bool = False
    window: WindowState | None = None

class Session(BaseModel):           # model_config: extra="allow"
    format: Literal["word-session"] = "word-session"
    version: Literal[1] = 1
    id: str
    name: str
    kind: SessionKind
    pinned: bool = False
    created_at: datetime            # must be timezone-aware (validator)
    host: str = ""
    word_version: str = ""
    notes: str = ""
    documents: list[DocumentState]

    def fingerprint(self) -> str: ...

class RestoreResult(BaseModel):
    path: str
    status: RestoreStatus
    message: str = ""

class RestoreReport(BaseModel):
    session_id: str
    dry_run: bool = False
    results: list[RestoreResult] = Field(default_factory=list)
    @property
    def ok(self) -> bool: ...       # True iff no result is missing/locked/failed

def classify_location(path: str) -> Location: ...
def slugify(name: str) -> str: ...
def make_session_id(created_at: datetime, name: str) -> str: ...
```

## Behaviour

- `classify_location`:
  - starts with `http://` or `https://` (case-insensitive) → `"url"`;
  - starts with `\\` → `"unc"`;
  - matches `^[A-Za-z]:[\\/]` → `"local"`;
  - anything else (e.g. `"Document1"`, `""`) → `"unsaved"`.
- `slugify`: NFKD-normalise, drop non-ASCII, lowercase, replace runs of
  non-`[a-z0-9]` with `-`, strip `-`, truncate to 40 chars (strip trailing
  `-` again); empty result → `"session"`.
- `make_session_id`: `created_at.strftime("%Y%m%dT%H%M%S") + "-" + slugify(name)`.
  Uniqueness is the store's job, not this function's.
- `Session.created_at` validator rejects naive datetimes with a clear
  message.
- `Session.fingerprint()`: SHA-256 hex of a canonical JSON of
  `[(d.path.casefold(), d.position.start, d.position.end, d.active) for d in documents]`
  (order-sensitive). Ignores id, name, timestamps. Used for autosave change
  detection.
- Unknown fields round-trip: `Session.model_validate(data).model_dump(mode="json")`
  keeps extra keys at session and document level.
- JSON dump uses ISO 8601 with offset for `created_at`.

## Tests (at least)

- each `classify_location` branch including `C:/x.docx`, `c:\x.docx`,
  `\\server\share\x.docx`, `https://contoso.sharepoint.com/x.docx`,
  `Document1`, `""`;
- `slugify` with non-ASCII (`"Thèse — chapitre 3"` → `"these-chapitre-3"`),
  symbols only, very long names;
- `make_session_id` format;
- naive datetime rejected; aware accepted;
- round-trip with unknown fields preserved;
- `fingerprint` equal for sessions differing only in name/id/created_at,
  different when a position or the path set changes, path compare is
  case-insensitive;
- `RestoreReport.ok` for all status combinations that matter;
- the JSON example in plan §3.3 validates.

## Do not

- No filesystem access, no Word, no logging in this module.

## Acceptance

README rule 7 commands.
