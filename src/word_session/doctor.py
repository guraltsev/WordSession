"""Diagnose why Word Session cannot reach Word or its own files.

Call ``run_checks(service, paths)`` to get one ``Check`` per diagnostic, in a
fixed order. A check that raises never stops the others; its exception
becomes a ``fail`` result carrying the message. The probes that touch the
operating system can be replaced, which keeps the checks testable on any
platform.
"""

import importlib.metadata
import importlib.util
import logging
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from word_session.config import AppPaths, load_settings
from word_session.service import SessionService

_log = logging.getLogger(__name__)


@dataclass
class Check:
    """Describe the result of one diagnostic.

    Attributes
    ----------
    name : str
        Short check name such as ``word-running``.
    status : Literal["ok", "warn", "fail"]
        Severity of the result.
    detail : str
        Human-readable explanation.
    """

    name: str
    status: Literal["ok", "warn", "fail"]
    detail: str


def run_checks(
    service: SessionService,
    paths: AppPaths,
    *,
    tasklist: Callable[[], str] | None = None,
    is_admin: Callable[[], bool] | None = None,
    word_registered: Callable[[], bool] | None = None,
) -> list[Check]:
    """Run every diagnostic and return the results in order.

    Parameters
    ----------
    service : SessionService
        Service used to ask Word for its state and to inspect the store.
    paths : AppPaths
        Application paths used for the configuration, log and marker checks.
    tasklist : Callable[[], str] | None
        Returns the output of ``tasklist /FI "IMAGENAME eq WINWORD.EXE" /NH``;
        defaults to running that command (empty text off Windows).
    is_admin : Callable[[], bool] | None
        Reports whether this process is elevated; defaults to the Windows
        shell check (always false elsewhere).
    word_registered : Callable[[], bool] | None
        Reports whether the ``Word.Application`` COM class is registered;
        defaults to a registry lookup (always false off Windows).

    Returns
    -------
    list[Check]
        Ten checks: python, pywin32, word-installed, word-running,
        word-process, elevated, sessions-dir, config, log.
    """
    tasklist = tasklist if tasklist is not None else _tasklist
    is_admin = is_admin if is_admin is not None else _is_admin
    word_registered = word_registered if word_registered is not None else _word_registered
    on_windows = sys.platform == "win32"

    def python() -> Check:
        return Check("python", "ok", f"{sys.version.split()[0]} at {sys.executable}")

    def pywin32() -> Check:
        # pywin32 is probed without importing it, which only com.py may do.
        if importlib.util.find_spec("win32com") is None:
            return Check("pywin32", "fail" if on_windows else "warn", "pywin32 is not installed")
        return Check("pywin32", "ok", f"version {importlib.metadata.version('pywin32')}")

    def word_installed() -> Check:
        if word_registered():
            return Check("word-installed", "ok", "Word.Application is registered")
        return Check(
            "word-installed",
            "fail" if on_windows else "warn",
            "Word.Application is not registered" + ("" if on_windows else " (not Windows)"),
        )

    def word_running() -> Check:
        if service.word_info().running:
            return Check("word-running", "ok", "Word is running and reachable")
        return Check("word-running", "warn", "Word is not running")

    def word_process() -> Check:
        # A WINWORD.EXE process that COM cannot see points to a privilege mismatch.
        process_exists = "winword.exe" in tasklist().lower()
        reachable = service.word_info().running
        if process_exists and not reachable:
            return Check(
                "word-process",
                "fail",
                "Word is running but not reachable over COM. This usually means Word and "
                "word-session run at different privilege levels (one as administrator).",
            )
        if process_exists:
            return Check("word-process", "ok", "WINWORD.EXE process found")
        return Check("word-process", "ok", "no WINWORD.EXE process")

    def elevated() -> Check:
        if is_admin():
            return Check("elevated", "warn", "running as administrator; Word usually is not")
        return Check("elevated", "ok", "not running as administrator")

    def sessions_dir() -> Check:
        # Prove the folder is writable by creating and removing a temp file.
        root = service.store.root
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=root, prefix=".doctor-"):
            pass
        count = len(service.store.list())
        invalid = len(service.store.list_invalid())
        detail = f"{root}: {count} sessions, {invalid} invalid files"
        return Check("sessions-dir", "warn" if invalid else "ok", detail)

    def config() -> Check:
        load_settings(paths.config_file)
        return Check("config", "ok", f"{paths.config_file} loads")

    def log() -> Check:
        return Check("log", "ok", str(paths.log_dir / "word-session.log"))

    # Run each check on its own so one failure is reported, not fatal.
    results: list[Check] = []
    probes = (
        python,
        pywin32,
        word_installed,
        word_running,
        word_process,
        elevated,
        sessions_dir,
        config,
        log,
    )
    for probe in probes:
        try:
            results.append(probe())
        except Exception as exc:
            _log.debug("check %s raised", probe.__name__, exc_info=exc)
            results.append(
                Check(probe.__name__.replace("_", "-"), "fail", str(exc) or type(exc).__name__)
            )
    return results


# ---- default probes -------------------------------------------------------


def _tasklist() -> str:
    """Return ``tasklist`` output for WINWORD.EXE (empty text off Windows)."""
    if sys.platform != "win32":
        return ""
    done = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq WINWORD.EXE", "/NH"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return done.stdout


def _is_admin() -> bool:
    """Return whether the process is elevated (always false off Windows)."""
    if sys.platform != "win32":
        return False
    import ctypes

    return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]


def _word_registered() -> bool:
    """Return whether the Word.Application COM class has a CLSID registry key."""
    try:
        import winreg
    except ImportError:
        return False
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID"))
    except OSError:
        return False
    return True
