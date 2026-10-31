# Job status

Edited only by the coordinator. States: `todo`, `in-progress`, `review`,
`done`, `blocked`. The run is autonomous (DECISIONS D8); job 22 is outside
the run and waits for the human.

| Job | Title | Depends on | Real Word | State | Attempts | Commit | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 00 | Git baseline | — | | done | 1 | 9841936 (tag legacy-baseline) | |
| 01 | Repository reorganisation | 00 | | done | 1 | 58a859a | |
| 02 | Project skeleton | 01 | | done | 1 | eb83c1c | |
| 03 | CI workflow | 02 | | done | 1 | 6f25d75 | not yet run remotely (no GitHub remote) |
| 04 | Data model | 02 | | done | 1 | e479f92 | |
| 05 | Session store | 04 | | done | 1 | c6b122a | |
| 06 | Legacy readers and import | 05 | | done | 1 | f6c0afe | |
| 07 | Config, paths, logging | 02 | | done | 1 | d5db01f | |
| 08 | Word backend protocol and fake | 04 | | done | 1 | 186fec8 | |
| 09 | COM backend | 08 | isolated + shared | done | 1 | c73bf70 | |
| 10 | COM worker | 08 | | done | 1 | 88ba64e | |
| 11 | Session service | 05, 06, 07, 10 | | done | 1 | 1bc55ed | |
| 12 | CLI core commands | 11 | | done | 1 | 6aa3a4f | |
| 13 | CLI management commands | 12 | | done | 1 | 9512545 | |
| 14 | End-to-end CLI tests against real Word | 09, 13 | isolated + shared | done | 1 | 9ab458a | |
| 15 | HTTP API | 11 | | done | 1 | d05e209 | |
| 16 | Web UI and `serve` | 15, 13 | | done | 1 | 88e7057 | |
| 17 | UI smoke tests (Playwright) | 16 | | done | 1 | 48be651 | |
| 18 | Tray app, single instance, `open`, autostart | 16 | | done | 1 | ec11781 | |
| 19 | Autosave | 18 | | done | 1 | 1d87e2a | |
| 20 | Packaging (PyInstaller) and `.cmd` shims | 19 | | done | 1 | 4039add | |
| 21 | Installer, user docs, release prep | 20 | | done | 1 | 1b29095 | installer.iss uncompiled (no iscc) |
| 23 | Human handoff | 21 | | done | 1 | 4e3dcf4 | final step of the run |
| 22 | Decommission legacy | 23 + human request | | todo | 0 | | outside the run |
