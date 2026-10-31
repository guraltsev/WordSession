"""Create or remove the per-user Start menu shortcut that starts Word Session.

``shortcut_path()`` names the shortcut in the user's own Start menu (or under
``WORD_SESSION_HOME`` when that is set), ``exists()`` reports whether it is
there, ``create()`` writes it and ``remove()`` deletes it. Nothing needs
administrator rights. The ``.lnk`` file is written by PowerShell through the
``WScript.Shell`` object, so this module needs no pywin32. Off Windows
``create()`` raises ``NotImplementedError``.
"""

import os
import subprocess
import sys
from pathlib import Path

from word_session import autostart

SHORTCUT_NAME = "Word Session.lnk"
DESCRIPTION = "Save and restore your open Word documents"

# Paths travel in environment variables so they never need PowerShell quoting.
_SCRIPT = (
    "$ErrorActionPreference = 'Stop';"
    "$link = (New-Object -ComObject WScript.Shell).CreateShortcut($env:WS_LINK);"
    "$link.TargetPath = $env:WS_TARGET;"
    "$link.Arguments = $env:WS_ARGUMENTS;"
    "$link.WorkingDirectory = $env:WS_WORKDIR;"
    "$link.IconLocation = $env:WS_ICON;"
    "$link.Description = $env:WS_DESCRIPTION;"
    "$link.Save()"
)


class ShortcutError(Exception):
    """Raised when the shortcut cannot be written."""


def supported() -> bool:
    """Return whether shortcuts can be created on this platform.

    Returns
    -------
    bool
        True on Windows.
    """
    return sys.platform == "win32"


def shortcut_path() -> Path:
    """Return where the Start menu shortcut lives.

    Returns
    -------
    Path
        ``%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Word Session.lnk``,
        or ``<WORD_SESSION_HOME>/start-menu/Word Session.lnk`` when
        ``WORD_SESSION_HOME`` is set (tests never touch the real Start menu).
    """
    home_env = os.environ.get("WORD_SESSION_HOME")
    if home_env:
        return Path(home_env) / "start-menu" / SHORTCUT_NAME
    appdata = os.environ.get("APPDATA")
    roaming = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs" / SHORTCUT_NAME


def exists() -> bool:
    """Return whether the shortcut file exists.

    Returns
    -------
    bool
        True when ``shortcut_path()`` is a file.
    """
    return shortcut_path().is_file()


def create() -> Path:
    """Write (or overwrite) the shortcut so it starts Word Session.

    Returns
    -------
    Path
        The shortcut file.

    Raises
    ------
    NotImplementedError
        Off Windows.
    ShortcutError
        If PowerShell could not write the shortcut.
    """
    if not supported():
        raise NotImplementedError("Start menu shortcuts are only supported on Windows")
    target, arguments = autostart.app_launcher(open_manager=True)
    link = shortcut_path()
    link.parent.mkdir(parents=True, exist_ok=True)
    _write_link(link, target, arguments)
    if not link.is_file():
        raise ShortcutError(f"the shortcut was not created at {link}")
    return link


def remove() -> bool:
    """Delete the shortcut; harmless when it is absent.

    Returns
    -------
    bool
        True when a shortcut was deleted.
    """
    link = shortcut_path()
    if not link.is_file():
        return False
    link.unlink()
    return True


def _write_link(link: Path, target: Path, arguments: str) -> None:
    """Write the ``.lnk`` file with PowerShell (a seam that tests replace)."""
    env = {
        **os.environ,
        "WS_LINK": str(link),
        "WS_TARGET": str(target),
        "WS_ARGUMENTS": arguments,
        "WS_WORKDIR": str(target.parent),
        "WS_ICON": f"{target},0",
        "WS_DESCRIPTION": DESCRIPTION,
    }
    command = ["powershell", "-NoProfile", "-NonInteractive", "-Command", _SCRIPT]
    try:
        subprocess.run(
            command,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
            # The tray app has no console; do not flash one for PowerShell.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip() or f"exit code {exc.returncode}"
        raise ShortcutError(f"could not create the shortcut: {detail}") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ShortcutError(f"could not create the shortcut: {exc}") from exc
