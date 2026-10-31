"""Start Word Session at login through the per-user Windows Run key.

``enable(command)`` registers a command, ``disable()`` removes it and
``is_enabled()`` reports whether one is registered. ``app_command()`` builds
the command that launches the application. Off Windows nothing is registered:
``is_enabled()`` is False and the other functions raise ``NotImplementedError``.
"""

import sys
from pathlib import Path
from typing import Any

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"  # per-user autostart key
VALUE_NAME = "WordSession"  # name of the value holding the command


def is_enabled() -> bool:
    """Return whether the autostart value exists.

    Returns
    -------
    bool
        True when the Run key holds a ``WordSession`` value; always False off
        Windows.
    """
    if sys.platform != "win32":
        return False
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    return True


def enable(command: str) -> None:
    """Register ``command`` to run at login.

    Parameters
    ----------
    command : str
        Full command line, quoted as needed.

    Raises
    ------
    NotImplementedError
        Off Windows.
    """
    winreg = _require_windows()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)


def disable() -> None:
    """Remove the autostart value; harmless when it is absent.

    Raises
    ------
    NotImplementedError
        Off Windows.
    """
    winreg = _require_windows()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass


def app_command() -> str:
    """Return the command line that starts the application.

    Returns
    -------
    str
        The quoted path of ``word-session.exe`` next to the running
        executable when frozen; otherwise ``"<python>" -m word_session app``
        (using ``pythonw.exe`` when it sits beside the interpreter so no
        console window appears).
    """
    target, arguments = app_launcher()
    return f'"{target}" {arguments}'.rstrip()


def app_launcher(*, open_manager: bool = False) -> tuple[Path, str]:
    """Return the program and the arguments that start the application.

    Parameters
    ----------
    open_manager : bool
        Also open the manager in the browser once started. The frozen
        ``word-session.exe`` always does, so this only adds ``--open``
        when running from source.

    Returns
    -------
    tuple of (Path, str)
        ``word-session.exe`` next to the running executable and no
        arguments when frozen; otherwise the interpreter (``pythonw.exe`` when
        it sits beside it) and ``-m word_session app``.
    """
    # A frozen build ships the windowed launcher next to the running exe.
    exe = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return exe.with_name("word-session.exe"), ""

    # From source, prefer the windowless interpreter and run the module.
    windowless = exe.with_name("pythonw.exe")
    interpreter = windowless if windowless.exists() else exe
    return interpreter, "-m word_session app" + (" --open" if open_manager else "")


def _require_windows() -> Any:
    """Return ``winreg`` or raise ``NotImplementedError`` off Windows."""
    if sys.platform != "win32":
        raise NotImplementedError("start at login is only supported on Windows")
    return _winreg()


def _winreg() -> Any:
    """Import ``winreg`` (a seam that tests replace)."""
    import winreg

    return winreg
