"""Command-line entry points for Word Session.

Call ``main(argv)`` to run the command-line interface and ``app_main()`` for
the windowless application launcher. This is a temporary stub that supports
only ``--version``.
"""

import argparse

from word_session import __version__


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface and return its exit code.

    Parameters
    ----------
    argv : list of str or None
        Command-line arguments without the program name; ``None`` uses
        ``sys.argv``.

    Returns
    -------
    int
        ``0`` after a successful command, ``2`` when no command is given.
    """
    parser = argparse.ArgumentParser(prog="word-session")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    args = parser.parse_args(argv)

    # Print the version when requested; otherwise show usage as a usage error.
    if args.version:
        print(f"word-session {__version__}")
        return 0
    parser.print_help()
    return 2


def app_main() -> None:
    """Start the application launcher and exit with its status code."""
    raise SystemExit(main(["app"]))
