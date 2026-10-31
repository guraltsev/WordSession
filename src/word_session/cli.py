"""Command-line interface for Word Session.

Call ``main(argv)`` to run a command and ``app_main()`` for the console
script. The everyday commands are ``save``, ``restore`` (alias ``load``),
``current``, ``list`` and ``show``. Add ``--json`` for one machine-readable
JSON document on stdout. Exit codes are stable: 0 success, 1 error, 2 usage,
3 Word unavailable, 4 partial restore, 5 session not found or ambiguous,
6 Word not responding.
"""

import argparse
import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from word_session import __version__
from word_session.config import ConfigError, app_paths, load_settings
from word_session.logging_setup import configure_logging
from word_session.model import DocumentState, RestoreReport, Session
from word_session.service import ServiceError, SessionService, open_service
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
    raise SystemExit(main(["app"]))


# ---- parser ---------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with global options and the five commands."""
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

    factory = service_factory if service_factory is not None else _default_service
    service = factory(args)
    try:
        handlers: dict[str, Callable[[argparse.Namespace, SessionService], _Outcome]] = {
            "save": _cmd_save,
            "restore": _cmd_restore,
            "load": _cmd_restore,
            "current": _cmd_current,
            "list": _cmd_list,
            "show": _cmd_show,
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
    lines = [
        f"{s.id}  {s.kind:<8} {len(s.documents):>3}  {s.name}" + ("  [pinned]" if s.pinned else "")
        for s in sessions
    ]
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
