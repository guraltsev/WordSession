# Job status

Edited only by the coordinator. States: `todo`, `in-progress`, `review`,
`done`, `blocked`. The run is autonomous (DECISIONS D8); job 22 is outside
the run and waits for the human.

| Job | Title | Depends on | Real Word | State | Attempts | Commit | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 00 | Git baseline | — | | todo | 0 | | |
| 01 | Repository reorganisation | 00 | | todo | 0 | | |
| 02 | Project skeleton | 01 | | todo | 0 | | |
| 03 | CI workflow | 02 | | todo | 0 | | |
| 04 | Data model | 02 | | todo | 0 | | |
| 05 | Session store | 04 | | todo | 0 | | |
| 06 | Legacy readers and import | 05 | | todo | 0 | | |
| 07 | Config, paths, logging | 02 | | todo | 0 | | |
| 08 | Word backend protocol and fake | 04 | | todo | 0 | | |
| 09 | COM backend | 08 | isolated + shared | todo | 0 | | |
| 10 | COM worker | 08 | | todo | 0 | | |
| 11 | Session service | 05, 06, 07, 10 | | todo | 0 | | |
| 12 | CLI core commands | 11 | | todo | 0 | | |
| 13 | CLI management commands | 12 | | todo | 0 | | |
| 14 | End-to-end CLI tests against real Word | 09, 13 | isolated + shared | todo | 0 | | |
| 15 | HTTP API | 11 | | todo | 0 | | |
| 16 | Web UI and `serve` | 15, 13 | | todo | 0 | | |
| 17 | UI smoke tests (Playwright) | 16 | | todo | 0 | | |
| 18 | Tray app, single instance, `open`, autostart | 16 | | todo | 0 | | |
| 19 | Autosave | 18 | | todo | 0 | | |
| 20 | Packaging (PyInstaller) and `.cmd` shims | 19 | | todo | 0 | | |
| 21 | Installer, user docs, release prep | 20 | | todo | 0 | | |
| 23 | Human handoff | 21 | | todo | 0 | | final step of the run |
| 22 | Decommission legacy | 23 + human request | | todo | 0 | | outside the run |
