"""Configure application logging to a rotating file and an optional console.

Call ``configure_logging(log_dir, console_level=...)`` once at startup. The
function is idempotent and never raises because of an unusable log directory.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Attribute that marks handlers installed by this module so they can be replaced.
_TAG = "_word_session_handler"


def configure_logging(log_dir: Path, *, console_level: int | None) -> None:
    """Install the file handler and, optionally, a stderr console handler.

    Parameters
    ----------
    log_dir : Path
        Directory for ``word-session.log``; created if missing.
    console_level : int or None
        Level for the stderr handler, or ``None`` for no console output.

    Notes
    -----
    Calling this again replaces the previously installed handlers. If the log
    directory cannot be used, only the console handler is installed and one
    warning is logged.
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Remove handlers from an earlier call so they are never duplicated.
    for old in [h for h in root.handlers if getattr(h, _TAG, False)]:
        root.removeHandler(old)
        old.close()

    # Open the rotating file; remember the failure to report it once below.
    file_error: OSError | None = None
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "word-session.log",
            maxBytes=1_000_000,
            backupCount=5,
            encoding="utf-8",
        )
    except OSError as exc:
        file_error = exc
    else:
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s")
        )
        setattr(file_handler, _TAG, True)
        root.addHandler(file_handler)

    # A failed file log still needs a visible channel for the warning.
    if console_level is None and file_error is not None:
        console_level = logging.WARNING

    # The console handler is only wanted by the CLI.
    if console_level is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setLevel(console_level)
        console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        setattr(console, _TAG, True)
        root.addHandler(console)

    if file_error is not None:
        logging.getLogger(__name__).warning(
            "Cannot write logs to %s (%s); logging to console only", log_dir, file_error
        )
