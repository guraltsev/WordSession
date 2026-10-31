# Session file format, version 1

A session is one UTF-8 JSON file named `<id>.json` in the sessions folder
(`%APPDATA%\word-session\sessions\` by default). Files use LF line endings and
are written to a temporary file and renamed, so a crash never leaves a
truncated session.

## Example

```json
{
  "format": "word-session",
  "version": 1,
  "id": "20261031T143000-thesis-chapter-3",
  "name": "Thesis chapter 3",
  "kind": "manual",
  "pinned": false,
  "created_at": "2026-10-31T14:30:00+01:00",
  "host": "LAPTOP-123",
  "word_version": "16.0",
  "notes": "",
  "documents": [
    {
      "path": "C:\\Users\\me\\Documents\\ch3.docx",
      "location": "local",
      "position": { "start": 18234, "end": 18234, "page": 12, "line": 7 },
      "active": true,
      "read_only": false,
      "had_unsaved_changes": false,
      "window": { "state": "maximized" }
    }
  ]
}
```

## Session fields

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `format` | string, always `"word-session"` | no (default) | Identifies the file type. |
| `version` | integer, always `1` | no (default) | Format version; see compatibility below. |
| `id` | string | yes | `YYYYMMDDTHHMMSS-slug` of the creation time and name; equals the file name without `.json`. Sorts chronologically. |
| `name` | string | yes | Display name chosen by the user or generated. |
| `kind` | `"manual"` or `"auto"` | yes | How the session came to be. Retention (pruning) applies only to `auto`. |
| `pinned` | boolean | no (`false`) | Protects the session from pruning. |
| `created_at` | ISO 8601 date-time with UTC offset | yes | Creation time. A value without an offset is rejected. |
| `host` | string | no (`""`) | Computer name that saved the session. |
| `word_version` | string | no (`""`) | Word's version, for example `"16.0"`. |
| `notes` | string | no (`""`) | Free text. |
| `documents` | array of documents | yes | Open documents in capture order (may be empty). |

## Document fields

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `path` | string | yes | Full name Word reports: a drive path, a UNC path or a URL. |
| `location` | `"local"`, `"unc"`, `"url"` or `"unsaved"` | yes | Kind of `path`. File-existence checks are made only for `local` and `unc`. `unsaved` documents (never saved, so no real path) are listed for information and skipped on restore. |
| `position` | object | no | Cursor position, below. |
| `active` | boolean | no (`false`) | This document was in front. It is restored last so it ends on top. |
| `read_only` | boolean | no (`false`) | The document was open read-only (including Protected View). |
| `had_unsaved_changes` | boolean | no (`false`) | It had unsaved edits when captured; restore opens the saved file. |
| `window` | object or null | no | Window state, below. |

### `position`

| Field | Type | Meaning |
| --- | --- | --- |
| `start`, `end` | integer or null | Character offsets of the selection (`Selection.Start` and `Selection.End`). Authoritative. |
| `page` | integer or null | 1-based page; null when Word reported no usable page. |
| `line` | integer or null | 1-based line on that page. |

Restore uses `start`/`end`. When they lie beyond the end of the document (it
was shortened), it falls back to `page` and `line`. These two also serve as a
human-readable hint in the manager.

### `window`

| Field | Type | Meaning |
| --- | --- | --- |
| `state` | `"normal"`, `"maximized"`, `"minimized"` or null | State of the document window. |

## Compatibility rules

- **Extra fields are preserved.** Unknown fields on a session or on a document
  are kept when Word Session rewrites the file (rename, pin, notes), so files
  written by newer versions are not damaged. Unknown fields inside `position`
  and `window` are ignored.
- **`version` gates migrations.** This release reads and writes `version: 1`.
  A file with another version, a different `format`, invalid JSON, or missing
  required fields is not loaded; it is reported and left untouched on disk.
- **Atomic writes.** A session is never edited in place; the new content
  replaces the old file in one rename.
- **Ids are unique.** If two sessions would get the same id, the store adds a
  numeric suffix. The ids of trashed sessions are not reused.
- **Deleting** moves the file to `trash\` in the sessions folder; the id stays
  reserved.

