# Local releases

`.gittools/release/release.py` makes releases from your own machine, with no CI involved: it bumps the version, tests,
builds the release files from exactly the committed `HEAD`, tags it, optionally publishes a GitHub release and checks
the uploaded bytes, and records every release in `RELEASES.md` with the SHA-256 of each published file.

```text
release.py bump [patch|minor|major|X.Y.Z]   raise the version in the version file and commit that file alone
release.py release ["notes"] [--local] [--dry-run] [--skip-tests]
release.py check [version] [--base-url URL]  compare a recorded release with its tags and published files
release.py status                            version, last release, what to do next (the default)
release.py init [--force]                    write a starter config.toml
```

The tool needs only Python 3.11+ and git. `gh` (signed in) is needed only when `[publish] github = true`.

## Setup

This folder is the whole tool. **Copy `.gittools/release/` into any git repository** and run, from inside it:

```sh
python .gittools/release/install.py
```

It asks whether to write a starter `config.toml` (the version file is guessed: `pyproject.toml`, `package.json`,
`Cargo.toml`, `VERSION`, or a Python `_version.py`/`__init__.py` with `__version__`; if none is found a `VERSION` file
with `0.1.0` is created) and launcher scripts `_scripts/release.cmd` / `.sh`. `--yes` takes the defaults, flags answer
the questions (`--init/--no-init`, `--launchers/--no-launchers`), nothing is overwritten without `--force`, and nothing
is committed. From outside a repository, `python install.py path/to/repo` copies this folder there first.

Then edit `config.toml` (test and build commands, assets), commit it, and look at the plan:

```sh
python .gittools/release/release.py release --dry-run
```

## A release

```sh
python .gittools/release/release.py bump            # 1.4.2 -> 1.4.3, committed as "Bump version to 1.4.3"
python .gittools/release/release.py release "Fixes the importer"
python .gittools/release/release.py check           # what the world can download matches the row
```

`release` releases the commit `HEAD`, with the version as it is in that commit. In order:

1. **Refuses**, before changing anything, when changes are staged, tracked files have edits (`require_clean`), the
   wrong branch is checked out (`branch`), the version is already in `RELEASES.md`, or the tag exists locally or on the
   remote. Publishing also requires `gh auth status` to succeed.
2. **Tests**: the `[test]` commands run in the checkout (where its `.venv` / `node_modules` live). A failure stops here.
3. **Builds** in a temporary worktree of `HEAD`, so uncommitted and untracked files cannot reach a release. The files
   matching `assets` are copied out (to `.git/release-assets/<tag>/` unless `output` says otherwise) with a
   `SHA256SUMS`. Every asset glob must match a file.
4. **Tags** `HEAD` (annotated, `v<version>` by default).
5. **Publishes** (`github = true`, not `--local`): pushes the tag, runs `gh release create` with the assets and
   `SHA256SUMS`, downloads them again and requires the same digests.
6. **Records** the row `| version | commit | date | assets (SHA-256) | notes |` at the top of `RELEASES.md` (created
   if missing) and commits that file alone. The row is written after publishing, so `RELEASES.md` never advertises a
   release that did not get out.
7. **Pushes** the branch with the row (`push_branch = true`, not `--local`).

If a step fails before the tag is pushed, the local tag is deleted and nothing else has changed. If it fails after the
tag was pushed, `RELEASES.md` is untouched and the error prints the three commands that undo the partial release
(`gh release delete`, delete the remote tag, delete the local tag).

`--local` (alias `--no-publish`) tags and records only, and prints the commands that publish it later.

## Configuration

All settings are in `config.toml` beside the script (`init` writes a commented one).

```toml
[version]
file = "pyproject.toml"
pattern = '''(?s)^\[project\]\s*$.*?^version\s*=\s*"([^"]+)"'''   # one group = the version; bump rewrites it

[release]
tag = "v{version}"
title = "{project} {version}"
file = "RELEASES.md"
branch = "main"           # "" allows every branch
remote = ""               # "" = the first remote
require_clean = true

[test]
command = "python -m pytest -q"          # or a list of arguments, or commands = [ ... ]

[build]
command = ["{root}/.venv/Scripts/python", "-m", "build", "--outdir", "dist"]
cwd = "."
env = { SOURCE_DATE_EPOCH = "0" }
assets = ["dist/*.whl", "dist/*.tar.gz"]  # globs in the worktree; empty = a tag-only release
output = ""                               # "" = .git/release-assets

[publish]
github = true
gh = "gh"                                 # or a list, e.g. ["gh", "--repo", "owner/name"]
push_branch = true
```

Placeholders work in the title, commands, `env` values and asset globs: `{version}`, `{tag}`, `{commit}`, `{project}`
(the repository folder name), `{root}` (the checkout), and in build commands also `{tree}` (the worktree) and `{out}`
(the asset folder). Commands also see them as `RELEASE_VERSION`, `RELEASE_TAG`, `RELEASE_COMMIT`, … `RELEASE_OUT`.
A string command runs through the shell; a list runs as arguments.

The worktree holds only committed files: no virtual environment, no installed packages. Reach the checkout's tools
with `{root}` (as above), or install them in the build command.

## `check`

Prints one PASS/FAIL line per check and exits 1 if any fails: the row exists; the local and the remote tag point at the
row's commit; the remote branch contains the commit that recorded the row; and, when publishing to GitHub (or with
`--base-url URL`, reading `URL/<name>`), every published asset and `SHA256SUMS` match the row's digests. It changes
nothing and does not fetch; if the remote branch tip is not in the clone it says to `git fetch`.

## Notes

- One version file only. If the version must appear in several places, have the build or the code read it from that
  one file.
- `bump` with `patch`/`minor`/`major` needs a `MAJOR.MINOR.PATCH` version; anything else takes an explicit version
  (`bump 2.0.0-rc.1`).
- The row records the commit that was tagged; the row itself is committed after it, so the tagged commit never contains
  its own row.
