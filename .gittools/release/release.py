"""Bump, build, tag, publish and record releases of a git repository, on the local machine.

``python .gittools/release/release.py bump [patch|minor|major|X.Y.Z]`` changes the version in
the one file named in ``config.toml`` and commits it. ``release.py release ["notes"]`` releases
the commit ``HEAD``: it runs the configured tests, builds the configured assets in a temporary
worktree of ``HEAD`` (so uncommitted or untracked files cannot reach them), tags the commit,
optionally pushes the tag, uploads the assets to a GitHub release with ``gh`` and downloads them
again to check the uploaded bytes, and finally adds a row with every asset's SHA-256 to
``RELEASES.md`` and commits it. ``release.py check [version]`` compares the tags and the
published assets with that row, and ``release.py status`` shows where the repository stands.

No step runs on a CI server. Only the Python standard library (3.11 or newer) and ``git`` are
needed; ``gh`` only when publishing to GitHub.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterator, Sequence

# Config file next to this script unless ``--config`` is given.
DEFAULT_CONFIG_PATH = Path(__file__).resolve().with_name("config.toml")

# What an explicit version may look like: dotted numbers with an optional pre-release or build suffix.
VERSION_SYNTAX = re.compile(r"[0-9]+(?:\.[0-9]+)*(?:[-+][0-9A-Za-z.+-]+)?")

# Header and separator of the release table; rows are inserted right below the separator, newest first.
TABLE_HEADER = "| Version | Commit | Date | Assets (SHA-256) | Notes |\n|---|---|---|---|---|"
_SEPARATOR = re.compile(r"(?m)^\|(?:\s*:?-+:?\s*\|){5}\s*$")

# Name of the checksum file written next to the assets and uploaded with them.
SUMS_NAME = "SHA256SUMS"


class ReleaseError(Exception):
    """A release step was refused or failed; the message says what state was left."""


@dataclass
class Config:
    """The settings of ``config.toml``; paths are relative to the repository root."""

    version_file: str
    version_pattern: re.Pattern[str]
    tag: str = "v{version}"
    title: str = "{project} {version}"
    releases_file: str = "RELEASES.md"
    branch: str = ""
    remote: str = ""
    require_clean: bool = True
    test: list = field(default_factory=list)
    test_env: dict = field(default_factory=dict)
    build: list = field(default_factory=list)
    build_cwd: str = "."
    build_env: dict = field(default_factory=dict)
    assets: list = field(default_factory=list)
    output: str = ""
    github: bool = False
    gh: list = field(default_factory=lambda: ["gh"])
    push_branch: bool = True


# ----------------------------------------------------------------------------
# Command-line entrypoint and the commands it dispatches to
# ----------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface and return its exit status.

    Parameters
    ----------
    argv : sequence of str, optional
        Arguments after the program name. Defaults to ``sys.argv[1:]``. Without a
        command, ``status`` is shown.

    Returns
    -------
    int
        ``0`` on success, ``1`` when a step is refused, fails or a check fails.
    """
    args = _parse_arguments(list(sys.argv[1:] if argv is None else argv))
    try:
        # The repository is the one that holds the config file, so the caller's directory does not matter.
        root = _repository_root(args.config.parent)
        if args.command == "init":
            return _command_init(root, args.config, force=args.force)
        config = load_config(args.config)
        if args.command == "bump":
            return bump(root, config, args.version, commit=not args.no_commit)
        if args.command == "release":
            return release(
                root,
                config,
                args.notes,
                local=args.local,
                run_tests=not args.skip_tests,
                dry_run=args.dry_run,
            )
        if args.command == "check":
            return check(root, config, args.version, base_url=args.base_url)
        return _command_status(root, config)
    except ReleaseError as error:
        print(f"release: {error}", file=sys.stderr)
        return 1


def load_config(path: Path) -> Config:
    """Read and validate ``config.toml``.

    Parameters
    ----------
    path : Path
        The settings file.

    Returns
    -------
    Config
        The settings, with defaults for every key that is not given.

    Raises
    ------
    ReleaseError
        If the file is missing, has unknown tables or keys, or the version pattern
        does not have exactly one group.
    """
    if not path.exists():
        raise ReleaseError(f"no settings file {path}; write one with: python {path.with_name('release.py')} init")
    data = tomllib.loads(path.read_text(encoding="utf-8"))

    # Reject typos instead of silently ignoring a setting.
    known = {
        "version": {"file", "pattern"},
        "release": {"tag", "title", "file", "branch", "remote", "require_clean"},
        "test": {"command", "commands", "env"},
        "build": {"command", "commands", "cwd", "env", "assets", "output"},
        "publish": {"github", "gh", "push_branch"},
    }
    for table, values in data.items():
        if table not in known or not isinstance(values, dict):
            raise ReleaseError(f"{path.name}: unknown table [{table}]")
        unknown = sorted(set(values) - known[table])
        if unknown:
            raise ReleaseError(f"{path.name}: unknown key(s) in [{table}]: {', '.join(unknown)}")

    # The version source is the only required setting; its pattern must capture exactly the version.
    version = data.get("version", {})
    if not version.get("file") or not version.get("pattern"):
        raise ReleaseError(f"{path.name}: [version] needs both file and pattern")
    pattern = re.compile(version["pattern"], re.MULTILINE)
    if pattern.groups != 1:
        raise ReleaseError(f"{path.name}: the version pattern must have exactly one group (it has {pattern.groups})")

    release_table, test, build, publish = (data.get(name, {}) for name in ("release", "test", "build", "publish"))
    gh = publish.get("gh", "gh")
    return Config(
        version_file=version["file"],
        version_pattern=pattern,
        tag=release_table.get("tag", "v{version}"),
        title=release_table.get("title", "{project} {version}"),
        releases_file=release_table.get("file", "RELEASES.md"),
        branch=release_table.get("branch", ""),
        remote=release_table.get("remote", ""),
        require_clean=bool(release_table.get("require_clean", True)),
        test=_command_list(test, f"{path.name} [test]"),
        test_env=dict(test.get("env", {})),
        build=_command_list(build, f"{path.name} [build]"),
        build_cwd=build.get("cwd", "."),
        build_env=dict(build.get("env", {})),
        assets=list(build.get("assets", [])),
        output=build.get("output", ""),
        github=bool(publish.get("github", False)),
        gh=[gh] if isinstance(gh, str) else list(gh),
        push_branch=bool(publish.get("push_branch", True)),
    )


def next_version(current: str, part: str) -> str:
    """Return the version that follows *current*.

    Parameters
    ----------
    current : str
        The version now in the version file.
    part : str
        ``patch``, ``minor`` or ``major`` to raise that number of a ``MAJOR.MINOR.PATCH``
        version, or an explicit new version.

    Returns
    -------
    str
        The new version.

    Raises
    ------
    ReleaseError
        If a number is to be raised in a version that is not ``MAJOR.MINOR.PATCH``, or
        an explicit version is malformed.
    """
    if part in ("patch", "minor", "major"):
        found = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)", current)
        if found is None:
            raise ReleaseError(f"cannot raise the {part} number of {current!r}: it is not MAJOR.MINOR.PATCH; give the new version")
        major, minor, patch = (int(number) for number in found.groups())
        if part == "major":
            return f"{major + 1}.0.0"
        if part == "minor":
            return f"{major}.{minor + 1}.0"
        return f"{major}.{minor}.{patch + 1}"
    if not VERSION_SYNTAX.fullmatch(part):
        raise ReleaseError(f"not a version: {part!r}")
    return part


def bump(root: Path, config: Config, target: str, *, commit: bool = True) -> int:
    """Write the next version into the version file and commit that file alone.

    Parameters
    ----------
    root : Path
        Repository root.
    config : Config
        Settings naming the version file and pattern.
    target : str
        ``patch``, ``minor``, ``major`` or an explicit version.
    commit : bool, optional
        Commit the change (default). Other staged changes are never included.

    Returns
    -------
    int
        ``0``.

    Raises
    ------
    ReleaseError
        If the version cannot be found or raised, is unchanged, or the version file
        has uncommitted edits that would be committed with it.
    """
    # Bytes in, bytes out, so the file keeps its line endings.
    path = root / config.version_file
    text = path.read_bytes().decode("utf-8")
    found = config.version_pattern.search(text)
    if found is None:
        raise ReleaseError(f"no version found in {config.version_file} (pattern {config.version_pattern.pattern!r})")
    current = found.group(1)
    new = next_version(current, target)
    if new == current:
        raise ReleaseError(f"the version is already {current}")

    # Edits already in the version file would ride along in the bump commit; refuse them.
    if commit and _git(["status", "--porcelain", "--", config.version_file], root):
        raise ReleaseError(f"{config.version_file} has uncommitted edits; commit or discard them first")

    path.write_bytes((text[: found.start(1)] + new + text[found.end(1) :]).encode("utf-8"))
    print(f"[release] {config.version_file}: {current} -> {new}")
    if commit:
        message = f"Bump version to {new}"
        _git(["add", "--", config.version_file], root)
        _git(["commit", "-q", "-m", message, "--", config.version_file], root)
        print(f"[release] committed \"{message}\". Release it with: {_self_command(root)} release")
    return 0


def release(
    root: Path,
    config: Config,
    notes: str | None = None,
    *,
    local: bool = False,
    run_tests: bool = True,
    dry_run: bool = False,
) -> int:
    """Test, build, tag, publish and record the release of ``HEAD``.

    Parameters
    ----------
    root : Path
        Repository root.
    config : Config
        Settings.
    notes : str, optional
        One line for the release table and the GitHub release; defaults to the title.
    local : bool, optional
        Tag and record only; push and upload nothing.
    run_tests : bool, optional
        Run the configured tests first (default).
    dry_run : bool, optional
        Run the checks and print the plan; change nothing.

    Returns
    -------
    int
        ``0`` when the release is recorded (or the plan was printed).

    Raises
    ------
    ReleaseError
        If a precondition fails (nothing is changed), or a step fails (the message
        says what was left and how to undo it).
    """
    # What is released: the commit HEAD and the version recorded in it, not in the working tree.
    commit = _git(["rev-parse", "HEAD"], root)
    version = _read_version(_git(["show", f"{commit}:{config.version_file}"], root), config, f"{config.version_file} at HEAD")
    values = {"version": version, "commit": commit, "project": root.name, "root": str(root)}
    tag = values["tag"] = _fill(config.tag, values)
    title = _fill(config.title, values)
    notes = " ".join((notes or title).replace("|", "/").split())
    publish = config.github and not local
    push = config.push_branch and not local
    remote = _remote(root, config) if (publish or push) else None
    if (publish or push) and remote is None:
        raise ReleaseError("no git remote is configured; add one or release with --local")
    releases = root / config.releases_file

    # Preconditions: everything that can be refused is refused before anything changes.
    if _git(["diff", "--cached", "--name-only"], root):
        raise ReleaseError("changes are staged; commit or unstage them first")
    if config.require_clean and _git(["status", "--porcelain", "--untracked-files=no"], root):
        raise ReleaseError("tracked files have uncommitted edits; commit or stash them (or set require_clean = false)")
    if _git(["status", "--porcelain", "--untracked-files=no", "--", config.releases_file], root):
        raise ReleaseError(f"{config.releases_file} has uncommitted edits; commit or discard them first")
    branch = _git(["branch", "--show-current"], root)
    if config.branch and branch != config.branch:
        raise ReleaseError(f"releases are made from {config.branch}, but {branch or 'a detached HEAD'} is checked out")
    if releases.exists() and _find_row(releases.read_text(encoding="utf-8"), version) is not None:
        raise ReleaseError(f"version {version} is already in {config.releases_file}; bump the version first")
    if _git_ok(["rev-parse", "--verify", "-q", f"refs/tags/{tag}"], root):
        raise ReleaseError(f"the tag {tag} already exists; bump the version first")
    if publish:
        if _git(["ls-remote", "--tags", remote, f"refs/tags/{tag}"], root):
            raise ReleaseError(f"{remote} already has the tag {tag}")
        if subprocess.run([*config.gh, "auth", "status"], cwd=root, capture_output=True).returncode != 0:
            raise ReleaseError(f"{' '.join(config.gh)} is not signed in (run: gh auth login), or release with --local")

    # A dry run stops here and says what would happen.
    out = _output_folder(root, config) / tag
    if dry_run:
        _print_plan(config, version, commit, tag, out, remote, publish=publish, push=push, run_tests=run_tests)
        return 0

    # Tests run in the checkout (where its environment lives); a failure ends the release untouched.
    if run_tests and config.test:
        try:
            _run_commands(config.test, root, config.test_env, values, "test")
        except ReleaseError as error:
            raise ReleaseError(f"{error}\nThe tests failed; nothing was released.") from None

    # Build from a worktree of HEAD and collect the assets outside it, then checksum them.
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    with _worktree(root, commit) as tree:
        build_values = {**values, "tree": str(tree), "out": str(out)}
        if config.build:
            _run_commands(config.build, tree / config.build_cwd, config.build_env, build_values, "build")
        assets = _collect_assets(tree, config.assets, out, build_values)
    if assets:
        (out / SUMS_NAME).write_bytes("".join(f"{digest}  {name}\n" for name, digest in assets).encode("ascii"))

    # Tag the released commit; from here on a failure says exactly what exists.
    _git(["tag", "-a", tag, "-m", title, commit], root)
    pushed = False
    try:
        if publish:
            _git(["push", remote, f"refs/tags/{tag}"], root)
            pushed = True
            files = [str(out / name) for name, _ in assets] + ([str(out / SUMS_NAME)] if assets else [])
            _run([*config.gh, "release", "create", tag, *files, "--title", title, "--notes", notes, "--verify-tag"], root)
            _verify_published(root, config, tag, assets)
    except ReleaseError as error:
        if not pushed:
            _git(["tag", "-d", tag], root, check=False)
            raise ReleaseError(f"{error}\nThe local tag {tag} was removed; nothing was published or recorded.") from None
        gh = " ".join(config.gh)
        raise ReleaseError(
            f"{error}\nThe tag {tag} is pushed to {remote}, but the release is incomplete and "
            f"{config.releases_file} was not changed. Undo it with:\n"
            f"  {gh} release delete {tag} --yes\n  git push {remote} :refs/tags/{tag}\n  git tag -d {tag}"
        ) from None

    # Record the release: the commit, the date and the digests of exactly the published bytes.
    cell = "<br>".join(f"`{digest}` {name}" for name, digest in assets) or "-"
    _insert_row(releases, f"| {version} | `{commit}` | {date.today().isoformat()} | {cell} | {notes} |")
    _git(["add", "--", config.releases_file], root)
    _git(["commit", "-q", "-m", f"Record release {version} in {config.releases_file}", "--", config.releases_file], root)
    print(f"[release] released {version} at {commit[:12]} as {tag}")
    for name, digest in assets:
        print(f"[release]   {digest}  {name}")
    if assets:
        print(f"[release] assets are in {out}")

    # Push the branch with the row, or say how to publish what stayed local.
    if push:
        if not _git_ok(["push", remote, "HEAD"], root):
            raise ReleaseError(f"the release is recorded locally, but pushing to {remote} failed; run: git push {remote} HEAD")
        print(f"[release] pushed {branch or 'HEAD'} to {remote}. Confirm with: {_self_command(root)} check")
    elif local:
        target = remote or "<remote>"
        print(f"[release] nothing was pushed or uploaded (--local). To publish it later:\n  git push {target} refs/tags/{tag} HEAD")
        if config.github:
            files = " ".join(f'"{out / name}"' for name, _ in assets) + (f' "{out / SUMS_NAME}"' if assets else "")
            print(f'  {" ".join(config.gh)} release create {tag} {files} --title "{title}" --notes "{notes}" --verify-tag')
    return 0


def check(root: Path, config: Config, version: str | None = None, *, base_url: str | None = None) -> int:
    """Compare a recorded release with the tags and the published assets.

    Prints one PASS or FAIL line per check. Nothing is changed or fetched into the
    repository.

    Parameters
    ----------
    root : Path
        Repository root.
    config : Config
        Settings.
    version : str, optional
        The release to check; defaults to the version in the working tree.
    base_url : str, optional
        Address holding the assets (``<base_url>/<name>``) instead of the GitHub release.

    Returns
    -------
    int
        ``0`` if every check passed, else ``1``.
    """
    lines: list[str] = []

    def report(ok: bool, text: str) -> bool:
        lines.append(f"{'PASS' if ok else 'FAIL'}  {text}")
        return ok

    def finish(ok: bool) -> int:
        print("\n".join(lines))
        print(f"{version}: {'all checks passed' if ok else 'CHECKS FAILED'}")
        return 0 if ok else 1

    # The row is the record everything else is compared with.
    path = root / config.version_file
    version = version or _read_version(path.read_text(encoding="utf-8"), config, config.version_file)
    releases = root / config.releases_file
    row = _find_row(releases.read_text(encoding="utf-8"), version) if releases.exists() else None
    if not report(row is not None, f"{config.releases_file} has a row for {version}"):
        return finish(False)
    commit, assets = row
    tag = _fill(config.tag, {"version": version, "project": root.name, "commit": commit, "root": str(root)})

    # Tags: local and remote must both name the released commit.
    local = _git(["rev-parse", "--verify", "-q", f"refs/tags/{tag}^{{commit}}"], root, check=False)
    ok = report(local == commit, f"the local tag {tag} points at the released commit {commit[:12]}")
    remote = _remote(root, config)
    if remote is None:
        ok &= report(False, "a git remote is configured")
    else:
        listed = _git(["ls-remote", remote, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"], root, check=False).split()
        peeled = listed[-2] if listed else ""
        ok &= report(peeled == commit, f"{remote} has the tag {tag} at the released commit")

        # The commit that added the row must be on the remote branch, or nobody else can see the row.
        added = _git(["log", "--format=%H", "-S", f"| {version} |", "--", config.releases_file], root).splitlines()
        branch = config.branch or _git(["branch", "--show-current"], root)
        tip = _git(["ls-remote", remote, f"refs/heads/{branch}"], root, check=False).split()
        if not added:
            ok &= report(False, f"the row for {version} is committed")
        elif not tip:
            ok &= report(False, f"{remote} has the branch {branch}")
        elif not _git_ok(["cat-file", "-e", f"{tip[0]}^{{commit}}"], root):
            ok &= report(False, f"{remote}/{branch} contains the row (its tip is not here: run git fetch {remote})")
        else:
            contained = _git_ok(["merge-base", "--is-ancestor", added[-1], tip[0]], root)
            ok &= report(contained, f"{remote}/{branch} contains the commit that recorded the row")

    # Published assets: download each and its checksum file, and compare with the row.
    if config.github or base_url:
        with tempfile.TemporaryDirectory(prefix="release-check-") as folder:
            names = [name for name, _ in assets] + ([SUMS_NAME] if assets else [])
            fetched = _download(root, config, tag, names, Path(folder), base_url)
            for name, digest in assets:
                actual = _sha256(fetched[name]) if name in fetched else None
                ok &= report(actual == digest, f"the published {name} has the SHA-256 of the row")
            if assets:
                listed = _parse_sums(fetched[SUMS_NAME].read_text(encoding="ascii")) if SUMS_NAME in fetched else {}
                ok &= report(listed == dict(assets), f"the published {SUMS_NAME} lists the same digests")
            else:
                lines.append(f"      {tag} has no assets; only the tags were checked")
    return finish(ok)


# ----------------------------------------------------------------------------
# Subcommands that do not release
# ----------------------------------------------------------------------------


def _command_status(root: Path, config: Config) -> int:
    """Print the version, the last release and what the next step is."""
    # The version in the working tree and at HEAD can differ while a bump is uncommitted.
    working = _read_version((root / config.version_file).read_text(encoding="utf-8"), config, config.version_file)
    committed = _read_version(_git(["show", f"HEAD:{config.version_file}"], root), config, f"{config.version_file} at HEAD")
    print(f"version      {committed} at HEAD" + ("" if working == committed else f", {working} in the working tree"))

    # The newest row of the table is the last release.
    releases = root / config.releases_file
    text = releases.read_text(encoding="utf-8") if releases.exists() else ""
    last = re.search(r"(?m)^\|\s*([^|\s]+)\s*\|\s*`([0-9a-f]{40})`\s*\|\s*([^|]*?)\s*\|", text)
    if last is None:
        print(f"last release none recorded in {config.releases_file}")
    else:
        tag = _fill(config.tag, {"version": last.group(1), "project": root.name, "commit": last.group(2), "root": str(root)})
        since = _git(["rev-list", "--count", f"{last.group(2)}..HEAD"], root, check=False) or "?"
        print(f"last release {last.group(1)} on {last.group(3)} ({tag}, {last.group(2)[:12]}); HEAD is {since} commit(s) after it")

    # Say which command comes next.
    if _find_row(text, committed) is not None:
        print(f"next         {committed} is released; bump the version: {_self_command(root)} bump")
    else:
        print(f"next         {committed} is not released yet: {_self_command(root)} release")
    return 0


def _command_init(root: Path, config_path: Path, *, force: bool) -> int:
    """Write a starter ``config.toml`` with the version source guessed from the project."""
    if config_path.exists() and not force:
        print(f"kept    {config_path.name} (exists; use --force to overwrite)")
        return 0

    # Find the file that holds the version; a project without one gets a VERSION file.
    file, pattern = _guess_version_source(root)
    created = file is None
    if created:
        file, pattern = "VERSION", r"\A\s*(\S+)"
        (root / file).write_text("0.1.0\n", encoding="utf-8", newline="\n")

    # A GitHub remote turns publishing on, any remote turns pushing on; the checked-out branch is the release branch.
    remotes = _git(["remote"], root).splitlines()
    url = _git(["remote", "get-url", remotes[0]], root) if remotes else ""
    branch = _git(["branch", "--show-current"], root) or "main"
    text = (
        _STARTER_CONFIG.replace("@FILE@", file)
        .replace("@PATTERN@", pattern)
        .replace("@BRANCH@", branch)
        .replace("@GITHUB@", "true" if "github.com" in url else "false")
        .replace("@PUSH@", "true" if remotes else "false")
    )
    config_path.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote   {config_path.relative_to(root).as_posix()} (version from {file})")
    if created:
        print("wrote   VERSION (0.1.0): no version was found in the project; commit it")
    return 0


# ----------------------------------------------------------------------------
# Building, publishing and recording
# ----------------------------------------------------------------------------


def _collect_assets(tree: Path, patterns: list[str], out: Path, values: dict[str, str]) -> list[tuple[str, str]]:
    """Copy the files matching *patterns* from *tree* into *out*; return ``(name, sha256)`` per file.

    Every pattern must match a file, and names must be unique, because assets are
    published flat under their file names.
    """
    assets: list[tuple[str, str]] = []
    for pattern in patterns:
        pattern = _fill(pattern, values)
        matches = sorted(path for path in tree.glob(pattern) if path.is_file())
        if not matches:
            raise ReleaseError(f"the asset pattern {pattern!r} matched no file after the build")
        for path in matches:
            if any(name == path.name for name, _ in assets):
                raise ReleaseError(f"two assets are named {path.name}; assets are published by file name")
            shutil.copyfile(path, out / path.name)
            assets.append((path.name, _sha256(out / path.name)))
    return assets


def _verify_published(root: Path, config: Config, tag: str, assets: list[tuple[str, str]]) -> None:
    """Download every uploaded asset of *tag* again and require the digests that will be recorded."""
    if not assets:
        return
    with tempfile.TemporaryDirectory(prefix="release-verify-") as folder:
        fetched = _download(root, config, tag, [name for name, _ in assets], Path(folder), None)
        for name, digest in assets:
            actual = _sha256(fetched[name]) if name in fetched else "nothing"
            if actual != digest:
                raise ReleaseError(f"the published {name} has SHA-256 {actual}, not {digest}")
    print(f"[release] verified the {len(assets)} published asset(s)")


def _download(root: Path, config: Config, tag: str, names: list[str], folder: Path, base_url: str | None) -> dict[str, Path]:
    """Download the assets *names* of *tag* into *folder*; return the ones that arrived, by name.

    With *base_url* the files are read from ``<base_url>/<name>`` (``https:`` or
    ``file:``); otherwise from the GitHub release with ``gh``, which also works for
    private repositories.
    """
    if base_url is None:
        patterns = [argument for name in names for argument in ("--pattern", name)]
        subprocess.run([*config.gh, "release", "download", tag, *patterns, "--dir", str(folder)], cwd=root, check=False)
    else:
        import urllib.request

        for name in names:
            url = f"{base_url.rstrip('/')}/{name}"
            if not url.startswith(("https://", "file:")):
                raise ReleaseError(f"refusing a non-https address: {url}")
            with contextlib.suppress(OSError), urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310
                (folder / name).write_bytes(response.read())
    return {name: folder / name for name in names if (folder / name).is_file()}


def _insert_row(releases: Path, row: str) -> None:
    """Add *row* at the top of the release table, creating the file or the table if needed."""
    if not releases.exists():
        releases.write_text(
            "# Releases\n\nEach row is one release: the version, the commit it was built from (and tagged), the date, "
            "and the SHA-256 of every published file. Newest first. Written by `.gittools/release/release.py`.\n\n"
            f"{TABLE_HEADER}\n{row}\n",
            encoding="utf-8",
            newline="\n",
        )
        return
    text = releases.read_bytes().decode("utf-8")
    separator = _SEPARATOR.search(text)
    if separator is None:
        text = text.rstrip("\n") + f"\n\n{TABLE_HEADER}\n{row}\n"
    else:
        newline = "\r\n" if "\r\n" in text else "\n"
        text = text[: separator.end()] + newline + row + text[separator.end() :]
    releases.write_bytes(text.encode("utf-8"))


def _find_row(text: str, version: str) -> tuple[str, list[tuple[str, str]]] | None:
    """Return the commit and the ``(name, sha256)`` assets of *version*'s row, or ``None``."""
    found = re.search(
        rf"(?m)^\|\s*{re.escape(version)}\s*\|\s*`([0-9a-f]{{40}})`\s*\|[^|\n]*\|([^|\n]*)\|",
        text,
    )
    if found is None:
        return None
    assets = re.findall(r"`([0-9a-f]{64})`\s+([^<|]+?)\s*(?=<br>|$)", found.group(2).strip())
    return found.group(1), [(name, digest) for digest, name in assets]


def _print_plan(config: Config, version: str, commit: str, tag: str, out: Path, remote: str | None, **steps: bool) -> None:
    """Describe what ``release`` would do, for ``--dry-run``."""
    def show(commands: list) -> str:
        return "; ".join(command if isinstance(command, str) else " ".join(command) for command in commands) or "none"

    print(f"[release] dry run: would release {version} (commit {commit[:12]}) as the tag {tag}")
    print(f"[release]   tests: {show(config.test) if steps['run_tests'] else 'skipped'}")
    print(f"[release]   build in a worktree of HEAD: {show(config.build)}")
    print(f"[release]   assets: {', '.join(config.assets) or 'none (a tag-only release)'} -> {out}")
    print(f"[release]   publish: {'GitHub release with ' + ' '.join(config.gh) + ' via ' + str(remote) if steps['publish'] else 'nothing'}")
    print(f"[release]   then add the row to {config.releases_file}, commit it" + (f" and push to {remote}" if steps["push"] else ""))


# ----------------------------------------------------------------------------
# Git, commands and small helpers
# ----------------------------------------------------------------------------


def _git(args: Sequence[str], cwd: Path, *, check: bool = True) -> str:
    """Run git and return its stripped output; raise ``ReleaseError`` on failure when *check*."""
    completed = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and completed.returncode != 0:
        raise ReleaseError(f"git {' '.join(args)} failed: {(completed.stderr or completed.stdout).strip()}")
    return completed.stdout.strip()


def _git_ok(args: Sequence[str], cwd: Path) -> bool:
    """Run git and return whether it succeeded."""
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True).returncode == 0


def _run(argv: list[str], cwd: Path) -> None:
    """Run a program, showing its output; raise ``ReleaseError`` if it fails."""
    completed = subprocess.run(argv, cwd=cwd)
    if completed.returncode != 0:
        raise ReleaseError(f"{' '.join(argv[:3])} ... failed (exit {completed.returncode})")


def _run_commands(commands: list, cwd: Path, env: dict, values: dict[str, str], what: str) -> None:
    """Run configured commands in order: a string through the shell, a list as arguments."""
    # The placeholders are also in the environment, so scripts can read them without arguments.
    environment = {**os.environ, **{f"RELEASE_{key.upper()}": value for key, value in values.items()}}
    environment.update({key: _fill(str(value), values) for key, value in env.items()})
    for command in commands:
        shell = isinstance(command, str)
        argv = _fill(command, values) if shell else [_fill(str(part), values) for part in command]
        shown = argv if shell else " ".join(argv)
        print(f"[release] {what}: {shown}", flush=True)
        completed = subprocess.run(argv, cwd=cwd, env=environment, shell=shell)
        if completed.returncode != 0:
            raise ReleaseError(f"the {what} command failed (exit {completed.returncode}): {shown}")


def _command_list(table: dict, where: str) -> list:
    """Return the commands of a ``[test]`` or ``[build]`` table: ``command`` or ``commands``."""
    if "command" in table and "commands" in table:
        raise ReleaseError(f"{where}: give command or commands, not both")
    if "commands" in table:
        return [command for command in table["commands"] if command]
    command = table.get("command", "")
    return [command] if command else []


@contextlib.contextmanager
def _worktree(root: Path, commit: str) -> Iterator[Path]:
    """Check *commit* out into a temporary detached worktree, yield its path, and remove it again."""
    with tempfile.TemporaryDirectory(prefix="release-") as folder:
        tree = Path(folder) / "tree"
        _git(["worktree", "add", "--detach", "-q", str(tree), commit], root)
        try:
            yield tree
        finally:
            _git(["worktree", "remove", "--force", str(tree)], root, check=False)
            _git(["worktree", "prune"], root, check=False)


def _output_folder(root: Path, config: Config) -> Path:
    """Where release assets are kept: ``[build] output``, else a folder inside the git directory."""
    if config.output:
        return (root / config.output).resolve()
    return (root / _git(["rev-parse", "--git-common-dir"], root)).resolve() / "release-assets"


def _read_version(text: str, config: Config, origin: str) -> str:
    """Return the version the pattern finds in *text* (read from *origin*)."""
    found = config.version_pattern.search(text)
    if found is None:
        raise ReleaseError(f"no version found in {origin} (pattern {config.version_pattern.pattern!r})")
    return found.group(1)


def _guess_version_source(root: Path) -> tuple[str | None, str]:
    """Return the first known file that holds a version and its pattern, or ``(None, "")``."""
    python_version = r"""^__version__\s*=\s*["']([^"']+)["']"""
    candidates = [
        ("pyproject.toml", r"""(?s)^\[project\]\s*$.*?^version\s*=\s*"([^"]+)\""""),
        ("package.json", r"""^\s*"version"\s*:\s*"([^"]+)\""""),
        ("Cargo.toml", r"""(?s)^\[package\]\s*$.*?^version\s*=\s*"([^"]+)\""""),
        ("VERSION", r"\A\s*(\S+)"),
    ]
    for pattern in ("src/*/_version.py", "*/_version.py", "src/*/__init__.py", "*/__init__.py"):
        candidates += [(path.relative_to(root).as_posix(), python_version) for path in sorted(root.glob(pattern))]
    for name, pattern in candidates:
        path = root / name
        if path.is_file() and not name.startswith(".") and re.search(pattern, path.read_text(encoding="utf-8", errors="replace"), re.MULTILINE):
            return name, pattern
    return None, ""


def _remote(root: Path, config: Config) -> str | None:
    """The configured remote, else the first one, else ``None``."""
    if config.remote:
        return config.remote
    remotes = _git(["remote"], root).splitlines()
    return remotes[0] if remotes else None


def _repository_root(start: Path) -> Path:
    """Return the top folder of the git repository containing *start*."""
    completed = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True)
    if completed.returncode != 0:
        raise ReleaseError(f"{start} is not inside a git repository")
    return Path(completed.stdout.strip()).resolve()


def _fill(text: str, values: dict[str, str]) -> str:
    """Replace the known ``{name}`` placeholders in *text*; other braces are left alone."""
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def _sha256(path: Path) -> str:
    """The SHA-256 of a file, as hex."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_sums(text: str) -> dict[str, str]:
    """Read a ``SHA256SUMS`` file into ``{name: sha256}``."""
    return {found.group(2): found.group(1) for found in re.finditer(r"(?m)^([0-9a-f]{64}) [ *](.+?)\s*$", text)}


def _self_command(root: Path) -> str:
    """How a person runs this tool from the repository root."""
    return f"python {Path(__file__).resolve().relative_to(root).as_posix()}" if Path(__file__).resolve().is_relative_to(root) else f"python {__file__}"


def _parse_arguments(argv: list[str]) -> argparse.Namespace:
    """Parse the command line; no command means ``status``."""
    parser = argparse.ArgumentParser(description="Bump, build, tag, publish and record releases, locally.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="settings file (default: config.toml beside this script)")
    commands = parser.add_subparsers(dest="command")

    bump_parser = commands.add_parser("bump", help="raise the version and commit it")
    bump_parser.add_argument("version", nargs="?", default="patch", help="patch (default), minor, major, or a version such as 1.4.0")
    bump_parser.add_argument("--no-commit", action="store_true", help="change the file only")

    release_parser = commands.add_parser("release", help="test, build, tag, publish and record HEAD")
    release_parser.add_argument("notes", nargs="?", help="one line for the table and the GitHub release (default: the title)")
    release_parser.add_argument("--local", "--no-publish", dest="local", action="store_true", help="tag and record only; push and upload nothing")
    release_parser.add_argument("--skip-tests", action="store_true", help="do not run the [test] commands")
    release_parser.add_argument("--dry-run", action="store_true", help="check and print the plan; change nothing")

    check_parser = commands.add_parser("check", help="compare a recorded release with its tags and published assets")
    check_parser.add_argument("version", nargs="?", help="release to check (default: the version in the working tree)")
    check_parser.add_argument("--base-url", help="read the assets from <base-url>/<name> instead of the GitHub release")

    commands.add_parser("status", help="show the version, the last release and the next step (default)")
    init_parser = commands.add_parser("init", help="write a starter config.toml")
    init_parser.add_argument("--force", action="store_true", help="overwrite an existing config.toml")

    args = parser.parse_args(argv)
    args.config = args.config.resolve()
    return args


# Starter config written by ``init``; the @NAMES@ are filled from the project.
_STARTER_CONFIG = """\
# Settings for .gittools/release/release.py. See README.md in this folder.
#
# Placeholders in titles, commands, env values and asset globs: {version}, {tag}, {commit},
# {project} (the repository folder name) and {root} (the checkout); build commands also get {tree}
# (the temporary worktree of HEAD) and {out} (where assets are collected). Commands see them as
# RELEASE_VERSION, RELEASE_TAG, RELEASE_COMMIT, RELEASE_PROJECT, RELEASE_ROOT, RELEASE_TREE, RELEASE_OUT.

[version]
# The one file that holds the version, and a regular expression (multi-line mode) whose single
# group is the version. `bump` rewrites exactly that group.
file = "@FILE@"
pattern = '''@PATTERN@'''

[release]
tag = "v{version}"
title = "{project} {version}"
file = "RELEASES.md"
# Refuse to release from any other branch ("" allows every branch).
branch = "@BRANCH@"
# Remote that receives the tag and the branch ("" means the first remote).
remote = ""
# Refuse when tracked files have uncommitted edits, so the tests run on exactly HEAD.
require_clean = true

[test]
# Runs in the checkout before anything changes; a failure stops the release. "" runs nothing.
# A shell string, a list of arguments, or commands = [ ... ] for several steps.
command = ""

[build]
# Runs in a temporary worktree of HEAD, so uncommitted and untracked files never reach the assets.
# The worktree has no untracked files: no .venv, no node_modules. Use {root} to reach the checkout's.
command = ""
cwd = "."
# Files to attach, as globs relative to the worktree, e.g. ["dist/*.zip"]. Every glob must match.
# Empty: a tag-only release.
assets = []
# Where assets and SHA256SUMS are kept, relative to the checkout ("" = .git/release-assets/<tag>).
output = ""

[publish]
# Push the tag, create the GitHub release with the assets (gh must be signed in) and download the
# assets again to check the uploaded bytes. false: tag and record locally only.
github = @GITHUB@
gh = "gh"
# After recording the row, push the branch to the remote.
push_branch = @PUSH@
"""


if __name__ == "__main__":
    sys.exit(main())
