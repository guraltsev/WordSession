"""Command-line interface for Word Session.

Call ``main(argv)`` to run a command and ``app_main()`` for the console
script. The everyday commands are ``save``, ``restore`` (alias ``load``),
``current``, ``list`` and ``show``; the management commands are ``rename``,
``delete``, ``pin``, ``unpin``, ``notes``, ``prune``, ``diff``,
``import-legacy`` and ``doctor``; ``serve`` runs the browser manager without
the tray, ``app`` runs the tray application, ``open`` opens the manager in
the browser (starting the application when needed) and ``quit-app`` stops the
running application. Add ``--json`` for one machine-readable
JSON document on stdout. Exit codes are stable: 0 success, 1 error, 2 usage,
3 Word unavailable, 4 partial restore, 5 session not found or ambiguous,
6 Word not responding.
"""

import argparse
import dataclasses
import json
import logging
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from word_session import __version__
from word_session.config import ConfigError, app_paths, load_settings
from word_session.doctor import run_checks
from word_session.instance import read_instance
from word_session.logging_setup import configure_logging
from word_session.model import DocumentState, RestoreReport, Session
from word_session.service import ServiceError, SessionService, first_run_import, open_service
from word_session.store import AmbiguousSelector, SessionNotFound, StoreError
from word_session.word.backend import WordError, WordNotResponding, WordUnavailable

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_WORD_UNAVAILABLE = 3
EXIT_PARTIAL_RESTORE = 4
EXIT_NOT_FOUND = 5
EXIT_NOT_RESPONDING = 6

_log = logging.getLogger(__name__)

# Set this event to make a running ``serve`` command shut down (tests use it;
# Ctrl+C does the same for a person).
serve_stop = threading.Event()


@dataclass
class _Outcome:
    """Everything a command wants printed, plus its exit code."""

    code: int = EXIT_OK
    data: object = None  # JSON-able payload for --json
    lines: list[str] = field(default_factory=list)  # human stdout
    warnings: list[str] = field(default_factory=list)  # human stderr


def main(
    argv: list[str] | None = None,
    *,
    service_factory: Callable[[argparse.Namespace], SessionService] | None = None,
) -> int:
    """Run the command-line interface and return its exit code.

    Parameters
    ----------
    argv : list of str or None
        Command-line arguments without the program name; ``None`` uses
        ``sys.argv``.
    service_factory : Callable[[argparse.Namespace], SessionService] or None
        Builds the service for a run (used by tests); the default opens the
        real or, with ``--demo``, the fake Word. The service is always closed
        afterwards.

    Returns
    -------
    int
        One of the ``EXIT_*`` codes.
    """
    # Parse arguments; argparse signals usage errors and --version by exiting.
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    if args.command is None:
        parser.print_help()
        return EXIT_USAGE

    # Windows consoles may not encode every character of a document path.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")

    # Run the command, mapping every failure to a stable exit code.
    try:
        outcome = _run(args, service_factory)
    except Exception as exc:
        outcome = _failure(args, exc)

    # Print the result in the requested format.
    if args.json:
        print(json.dumps(outcome.data))
    else:
        if not args.quiet:
            for line in outcome.lines:
                print(line)
        if outcome.code != EXIT_OK or not args.quiet:
            for line in outcome.warnings:
                print(line, file=sys.stderr)
    return outcome.code


def app_main() -> None:
    """Start the application launcher and exit with its status code."""
    raise SystemExit(main(["app", "--open"]))


# ---- parser ---------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with global options and all commands."""
    parser = argparse.ArgumentParser(
        prog="word-session", description="Save and restore Word sessions."
    )
    parser.add_argument("--version", action="version", version=f"word-session {__version__}")
    parser.add_argument("--json", action="store_true", help="machine-readable output on stdout")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging and tracebacks")
    parser.add_argument("-q", "--quiet", action="store_true", help="only errors on stderr")
    parser.add_argument("--config", metavar="PATH", help="settings file")
    parser.add_argument("--sessions-dir", metavar="DIR", help="override the sessions directory")
    parser.add_argument("--demo", action="store_true", help="use the fake Word backend")
    commands = parser.add_subparsers(dest="command", metavar="<command>")

    save = commands.add_parser("save", help="save the open Word documents as a session")
    save.add_argument("--name", help="session name")

    for name, help_text in (
        ("restore", "reopen the documents of a session"),
        ("load", "alias of restore"),
    ):
        restore = commands.add_parser(name, help=help_text)
        restore.add_argument("selector", nargs="?", default="latest", help="default: latest")
        restore.add_argument(
            "--only", action="append", metavar="GLOB", help="restore matching only"
        )
        restore.add_argument("--no-start", action="store_true", help="do not start Word")
        restore.add_argument("--no-position", action="store_true", help="do not move cursors")
        restore.add_argument("--dry-run", action="store_true", help="report without opening")

    commands.add_parser("current", help="list the documents open in Word")

    list_cmd = commands.add_parser("list", help="list saved sessions, newest first")
    list_cmd.add_argument("--limit", type=int, default=20, help="default: 20")
    list_cmd.add_argument("--kind", choices=["manual", "auto", "imported"])

    show = commands.add_parser("show", help="show one session")
    show.add_argument("selector")

    # Management commands.
    rename = commands.add_parser("rename", help="rename a session")
    rename.add_argument("selector")
    rename.add_argument("new_name")

    delete = commands.add_parser("delete", help="move a session to the trash")
    delete.add_argument("selector")
    delete.add_argument("--purge", action="store_true", help="delete permanently")
    delete.add_argument("--yes", action="store_true", help="do not ask for confirmation")

    for name, help_text in (("pin", "protect a session from pruning"), ("unpin", "undo pin")):
        commands.add_parser(name, help=help_text).add_argument("selector")

    notes = commands.add_parser("notes", help="set the notes of a session")
    notes.add_argument("selector")
    notes.add_argument("text")

    prune = commands.add_parser("prune", help="trash old automatic sessions")
    prune.add_argument("--keep", type=int, help="automatic sessions to keep (default: settings)")

    diff = commands.add_parser("diff", help="compare the documents of two sessions")
    diff.add_argument("selector_a")
    diff.add_argument("selector_b")

    legacy = commands.add_parser("import-legacy", help="import sessions of the old tools")
    legacy.add_argument("dirs", nargs="*", metavar="DIR", help="default: the old tools' folders")

    commands.add_parser("doctor", help="explain why Word cannot be reached")

    serve = commands.add_parser("serve", help="run the browser manager without the tray")
    serve.add_argument("--port", type=int, default=0, help="TCP port (default: a free one)")
    serve.add_argument("--open", action="store_true", help="open the manager in the browser")
    serve.add_argument(
        "--no-import", action="store_true", help="do not import the old tools' sessions"
    )

    app = commands.add_parser("app", help="run the tray application")
    app.add_argument("--open", action="store_true", help="open the manager once started")
    commands.add_parser("open", help="open the manager in the browser")
    commands.add_parser(
        "quit-app", help="stop the running tray application (used by the installer)"
    )
    return parser


# ---- running a command ----------------------------------------------------


def _run(
    args: argparse.Namespace,
    service_factory: Callable[[argparse.Namespace], SessionService] | None,
) -> _Outcome:
    """Configure logging, build the service, run the command and close it."""
    # Console log level follows -v / -q; the file log always records everything.
    console_level = (
        logging.DEBUG if args.verbose else logging.ERROR if args.quiet else logging.WARNING
    )
    configure_logging(app_paths().log_dir, console_level=console_level)

    # The tray application and ``open`` manage their own service (or need none).
    if args.command == "app":
        return _cmd_app(args)
    if args.command == "open":
        return _cmd_open(args)
    if args.command == "quit-app":
        return _cmd_quit_app()

    factory = service_factory if service_factory is not None else _default_service
    service = factory(args)
    try:
        # Bring old sessions in once, before any command that reads the store.
        if args.command not in ("doctor", "import-legacy", "serve", "app", "open"):
            _announce_first_run_import(args, service)
        handlers: dict[str, Callable[[argparse.Namespace, SessionService], _Outcome]] = {
            "save": _cmd_save,
            "restore": _cmd_restore,
            "load": _cmd_restore,
            "current": _cmd_current,
            "list": _cmd_list,
            "show": _cmd_show,
            "rename": _cmd_update,
            "pin": _cmd_update,
            "unpin": _cmd_update,
            "notes": _cmd_update,
            "delete": _cmd_delete,
            "prune": _cmd_prune,
            "diff": _cmd_diff,
            "import-legacy": _cmd_import_legacy,
            "doctor": _cmd_doctor,
            "serve": _cmd_serve,
        }
        return handlers[args.command](args, service)
    finally:
        service.close()


def _default_service(args: argparse.Namespace) -> SessionService:
    """Open the real (or demo) service honouring ``--config`` and ``--sessions-dir``."""
    config = Path(args.config) if args.config else app_paths().config_file
    settings = load_settings(config)
    if args.sessions_dir:
        settings = settings.model_copy(update={"sessions_dir": Path(args.sessions_dir)})
    return open_service(settings=settings, fake=args.demo)


def _announce_first_run_import(args: argparse.Namespace, service: SessionService) -> None:
    """Run the one-time legacy import and tell the user when it found sessions."""
    # A broken legacy folder must never stop the command the user asked for.
    try:
        summary = first_run_import(service, app_paths())
    except Exception as exc:
        _log.warning("first-run import failed: %s", exc, exc_info=exc)
        return
    if summary is not None and summary.imported and not args.quiet:
        print(
            f"Imported {len(summary.imported)} sessions from the old word-session tools.",
            file=sys.stderr,
        )


def _failure(args: argparse.Namespace, exc: Exception) -> _Outcome:
    """Translate an exception into an exit code and a one-line message."""
    # Pick the exit code and, for known errors, the message to show.
    message = str(exc) or type(exc).__name__
    warnings: list[str] = []
    known = True
    if isinstance(exc, WordUnavailable):
        code = EXIT_WORD_UNAVAILABLE
        message = "Word is not running"
        if getattr(args, "no_start", False):
            warnings.append("hint: start Word or omit --no-start")
        elif getattr(args, "command", None) in ("restore", "load"):
            warnings.append("hint: start Word and try again")
    elif isinstance(exc, WordNotResponding):
        code = EXIT_NOT_RESPONDING
    elif isinstance(exc, AmbiguousSelector):
        code = EXIT_NOT_FOUND
        warnings.extend(f"  candidate: {c}" for c in exc.candidates)
    elif isinstance(exc, SessionNotFound):
        code = EXIT_NOT_FOUND
    elif isinstance(exc, ConfigError | StoreError | ServiceError | WordError):
        code = EXIT_ERROR
    else:
        code = EXIT_ERROR
        known = False

    # Keep the traceback in the log file; with -v the DEBUG console shows it too.
    _log.debug("command failed: %s", message, exc_info=exc)
    if not known:
        message = f"unexpected error, see {app_paths().log_dir / 'word-session.log'}"
    lines = [f"error: {message}", *warnings]
    data = {"error": {"type": type(exc).__name__, "message": str(exc) or message}}
    return _Outcome(code=code, data=data, warnings=lines)


# ---- commands -------------------------------------------------------------


def _cmd_save(args: argparse.Namespace, service: SessionService) -> _Outcome:
    """Capture the open documents as a new session."""
    result = service.capture(args.name)
    data = {
        "session": result.session.model_dump(mode="json"),
        "warnings": result.warnings,
        "path": str(result.path) if result.path is not None else None,
    }

    # An empty Word is not an error; just say nothing was saved.
    if result.path is None:
        return _Outcome(data=data, lines=["Word has no open documents; nothing saved"])
    count = len(result.session.documents)
    noun = "document" if count == 1 else "documents"
    return _Outcome(
        data=data,
        lines=[f'Saved "{result.session.name}" ({count} {noun}) -> {result.path}'],
        warnings=[f"warning: {w}" for w in result.warnings],
    )


def _cmd_restore(args: argparse.Namespace, service: SessionService) -> _Outcome:
    """Restore a session and map a partial result to exit code 4."""
    report = service.restore(
        args.selector,
        only=args.only,
        start_word=False if args.no_start else None,
        restore_position=False if args.no_position else None,
        dry_run=args.dry_run,
    )
    return _Outcome(
        code=EXIT_OK if report.ok else EXIT_PARTIAL_RESTORE,
        data=report.model_dump(mode="json"),
        lines=_restore_lines(report),
    )


def _restore_lines(report: RestoreReport) -> list[str]:
    """Format one line per result and a summary of counts per status."""
    lines = [
        f"{r.status:<11} {r.path}" + (f"  ({r.message})" if r.message else "")
        for r in report.results
    ]

    # Count statuses in order of first appearance for the summary line.
    counts: dict[str, int] = {}
    for result in report.results:
        counts[result.status] = counts.get(result.status, 0) + 1
    lines.append(", ".join(f"{n} {status}" for status, n in counts.items()) or "nothing to restore")
    return lines


def _cmd_current(args: argparse.Namespace, service: SessionService) -> _Outcome:
    """List the documents open in Word."""
    documents = service.current()
    lines = [_document_line(d) for d in documents]
    return _Outcome(data=[d.model_dump(mode="json") for d in documents], lines=lines)


def _document_line(doc: DocumentState) -> str:
    """Format a document with an active marker and its page and line."""
    text = f"{'*' if doc.active else ' '} {doc.path}"
    pos = doc.position
    if pos.page is not None:
        text += f"  p. {pos.page}" + (f", l. {pos.line}" if pos.line is not None else "")
    return text


def _cmd_list(args: argparse.Namespace, service: SessionService) -> _Outcome:
    """List stored sessions, newest first."""
    sessions = service.list_sessions(kind=args.kind)[: max(args.limit, 0)]
    lines = [_session_line(s) for s in sessions]
    return _Outcome(data=[s.model_dump(mode="json") for s in sessions], lines=lines)


def _cmd_show(args: argparse.Namespace, service: SessionService) -> _Outcome:
    """Show a session's header and its documents."""
    session = service.get(args.selector)
    return _Outcome(
        data=session.model_dump(mode="json"), lines=_show_lines(session, demo=args.demo)
    )


def _show_lines(session: Session, *, demo: bool) -> list[str]:
    """Format the session header and one line per document."""
    lines = [
        f"Name:    {session.name}",
        f"Id:      {session.id}",
        f"Kind:    {session.kind}",
        f"Created: {session.created_at.isoformat()}",
        f"Host:    {session.host}",
        f"Notes:   {session.notes}",
        "Documents:",
    ]

    # Only local and UNC files can be checked on disk; the demo has none.
    for doc in session.documents:
        flag = ""
        if doc.location in ("local", "unc"):
            flag = "  exists" if demo or Path(doc.path).exists() else "  MISSING"
        lines.append(f"  {_document_line(doc)}  [{doc.location}]{flag}")
    return lines


# ---- management commands --------------------------------------------------


def _session_line(session: Session) -> str:
    """Format a session as one line for ``list`` and the update commands."""
    pinned = "  [pinned]" if session.pinned else ""
    return f"{session.id}  {session.kind:<8} {len(session.documents):>3}  {session.name}{pinned}"


def _cmd_update(args: argparse.Namespace, service: SessionService) -> _Outcome:
    """Apply rename, pin, unpin or notes through ``service.update``."""
    # Each command changes exactly one field.
    if args.command == "rename":
        session = service.update(args.selector, name=args.new_name)
    elif args.command == "notes":
        session = service.update(args.selector, notes=args.text)
    else:
        session = service.update(args.selector, pinned=args.command == "pin")
    return _Outcome(data=session.model_dump(mode="json"), lines=[_session_line(session)])


def _cmd_delete(args: argparse.Namespace, service: SessionService) -> _Outcome:
    """Delete a session after confirmation, to the trash unless ``--purge``."""
    session = service.get(args.selector)

    # Ask on a terminal; scripts must opt in with --yes.
    if not args.yes:
        if not sys.stdin.isatty():
            message = "refusing to delete without confirmation; use --yes"
            return _Outcome(
                code=EXIT_USAGE,
                data={"error": {"type": "UsageError", "message": message}},
                warnings=[f"error: {message}"],
            )
        answer = input(f'Delete "{session.name}" ({session.id})? [y/N] ')
        if answer.strip().lower() not in ("y", "yes"):
            return _Outcome(
                code=EXIT_ERROR,
                data={"deleted": None, "cancelled": True},
                warnings=["cancelled"],
            )

    # Delete, then say where the file went.
    service.delete(session.id, purge=args.purge)
    trash = None if args.purge else service.store.trash_dir / f"{session.id}.json"
    if trash is None:
        line = f'Deleted "{session.name}" ({session.id}) permanently'
    else:
        line = f'Moved "{session.name}" ({session.id}) to the trash: {trash}'
    data = {
        "deleted": session.id,
        "purged": args.purge,
        "trash": str(trash) if trash is not None else None,
    }
    return _Outcome(data=data, lines=[line])


def _cmd_prune(args: argparse.Namespace, service: SessionService) -> _Outcome:
    """Trash old automatic sessions and list the removed ids."""
    removed = service.prune(args.keep)
    return _Outcome(data={"removed": removed}, lines=removed or ["nothing to prune"])


def _cmd_diff(args: argparse.Namespace, service: SessionService) -> _Outcome:
    """Show the document paths added and removed between two sessions."""
    result = service.diff(args.selector_a, args.selector_b)
    lines = [f"+ {p}" for p in result.added] + [f"- {p}" for p in result.removed]
    return _Outcome(data=dataclasses.asdict(result), lines=lines)


def _cmd_import_legacy(args: argparse.Namespace, service: SessionService) -> _Outcome:
    """Import sessions from the old tools and report counts and errors."""
    dirs = [Path(d) for d in args.dirs] if args.dirs else None
    summary = service.import_legacy(dirs)
    data = {
        "imported": summary.imported,
        "skipped": [str(p) for p in summary.skipped],
        "errors": [{"path": str(p), "message": m} for p, m in summary.errors],
    }
    line = (
        f"Imported {len(summary.imported)} sessions, skipped {len(summary.skipped)}, "
        f"{len(summary.errors)} errors"
    )
    return _Outcome(
        data=data,
        lines=[line],
        warnings=[f"error: {p}: {m}" for p, m in summary.errors],
    )


def _cmd_doctor(args: argparse.Namespace, service: SessionService) -> _Outcome:
    """Run the diagnostics; exit 1 when any check fails."""
    checks = run_checks(service, app_paths())
    labels = {"ok": "ok", "warn": "warn", "fail": "FAIL"}
    lines = [f"{labels[c.status]:<4} {c.name:<15} {c.detail}" for c in checks]
    failed = any(c.status == "fail" for c in checks)
    return _Outcome(
        code=EXIT_ERROR if failed else EXIT_OK,
        data=[dataclasses.asdict(c) for c in checks],
        lines=lines,
    )


def _cmd_serve(args: argparse.Namespace, service: SessionService) -> _Outcome:
    """Serve the API and web UI until Ctrl+C (or ``serve_stop``) and exit 0."""
    # Imported here so other commands never load the web stack.
    from word_session.web.server import start_server

    # Bring old sessions in once, unless the user opted out.
    if not args.no_import:
        _announce_first_run_import(args, service)

    # Reset the stop flag before the server exists, so a stop request made as
    # soon as the server is reachable can never be lost.
    serve_stop.clear()

    # Start the server and mint the one-time link that signs a browser in.
    handle = start_server(service, port=args.port)
    url = f"{handle.url}/login?code={handle.auth.mint_login_code()}"

    # Human messages go to stderr under --json so stdout stays one document.
    out = sys.stderr if args.json else sys.stdout
    print(f"Word Session manager: {url}", file=out)
    print("Press Ctrl+C to stop", file=out, flush=True)
    if args.open:
        webbrowser.open(url)

    # Wait in short slices: a blocking wait would not see Ctrl+C on Windows.
    try:
        while not serve_stop.wait(0.25):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        handle.stop()
    return _Outcome(data={"url": handle.url, "stopped": True})


def _cmd_app(args: argparse.Namespace) -> _Outcome:
    """Run the tray application until the user quits."""
    # Imported here so other commands never load the tray stack.
    from word_session.app import App

    code = App(fake=args.demo, open_browser=args.open).run()
    return _Outcome(code=code, data={"exit": code})


def _cmd_quit_app() -> _Outcome:
    """Ask the running application to quit and wait until it has gone.

    Exits 0 when nothing was running; exits 1 when the instance file is still
    there after five seconds.
    """
    # No instance file means nothing to stop.
    instance_file = app_paths().instance_file
    info = read_instance(instance_file)
    if info is None:
        return _Outcome(data={"was_running": False}, lines=["Word Session is not running"])

    # Ask the instance to shut down; a stale file (nobody answers) counts as stopped.
    request = urllib.request.Request(
        f"http://127.0.0.1:{info.port}/api/internal/shutdown",
        data=b"",
        method="POST",
        headers={"X-Word-Session-Secret": info.secret},
    )
    try:
        urllib.request.urlopen(request, timeout=3.0).close()
    except OSError:
        _log.debug("recorded instance does not answer", exc_info=True)
        return _Outcome(data={"was_running": False}, lines=["Word Session is not running"])

    # The application removes its instance file as it exits.
    deadline = time.monotonic() + 5.0
    while instance_file.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    if instance_file.exists():
        raise ServiceError("Word Session did not stop within 5 seconds")
    return _Outcome(data={"was_running": True}, lines=["Word Session stopped"])


def _cmd_open(args: argparse.Namespace) -> _Outcome:
    """Open the manager in the browser, starting the application if needed."""
    from word_session import autostart
    from word_session.instance import request_login_url

    # Prefer the running instance: it mints a login code for a new tab.
    info = read_instance(app_paths().instance_file)
    if info is not None:
        try:
            url = request_login_url(info)
        except ConnectionError:
            _log.debug("recorded instance does not answer", exc_info=True)
        else:
            webbrowser.open(url)
            return _Outcome(data={"url": url, "started": False}, lines=[url])

    # Nobody answered: start the application detached; it opens the manager.
    if args.demo:
        command = f'"{sys.executable}" -m word_session --demo app --open'
    else:
        command = f"{autostart.app_command()} --open"
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    subprocess.Popen(command, creationflags=flags, close_fds=True)
    return _Outcome(
        data={"url": None, "started": True}, lines=["Starting Word Session; the manager will open"]
    )
