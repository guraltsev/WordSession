"""Single-instance bookkeeping for the Word Session application.

``InstanceLock`` lets exactly one application process run per user (a named
mutex on Windows, an exclusive lock file elsewhere). The running process
records how to reach it with ``write_instance``; other processes find it with
``read_instance`` and obtain a browser login URL with ``request_login_url``.
"""

import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MUTEX_NAME = "Local\\WordSession.App"  # per-user named mutex of the application


@dataclass
class InstanceInfo:
    """Describe how to reach the running application instance.

    Attributes
    ----------
    pid : int
        Process id of the instance.
    port : int
        Port of its local HTTP server.
    secret : str
        The server's ``Auth.instance_secret``.
    version : str
        Application version of the instance.
    """

    pid: int
    port: int
    secret: str
    version: str


class InstanceLock:
    """Allow only one application instance per user.

    Parameters
    ----------
    lock_path : Path or None
        Lock file used when no named mutex is available; defaults to
        ``instance.lock`` next to the instance file.
    use_mutex : bool or None
        Use the Windows named mutex; defaults to True on Windows only.
    mutex_name : str
        Name of the mutex.

    Notes
    -----
    The lock file holds the owner's pid; a file whose pid is not running is
    stale and is taken over.
    """

    def __init__(
        self,
        lock_path: Path | None = None,
        *,
        use_mutex: bool | None = None,
        mutex_name: str = MUTEX_NAME,
    ) -> None:
        if lock_path is None:
            from word_session.config import app_paths

            lock_path = app_paths().instance_file.with_suffix(".lock")
        self._path = lock_path
        self._use_mutex = sys.platform == "win32" if use_mutex is None else use_mutex
        self._mutex_name = mutex_name
        self._mutex: Any = None
        self._held = False

    def acquire(self) -> bool:
        """Try to become the single instance.

        Returns
        -------
        bool
            True when this object now holds the lock, False when another
            instance holds it.
        """
        if self._held:
            return True
        self._held = self._acquire_mutex() if self._use_mutex else self._acquire_file()
        return self._held

    def release(self) -> None:
        """Give the lock up; harmless when it is not held."""
        if not self._held:
            return
        self._held = False

        # Close the mutex handle or remove our lock file.
        if self._mutex is not None:
            import win32api

            win32api.CloseHandle(self._mutex)
            self._mutex = None
        else:
            self._path.unlink(missing_ok=True)

    def _acquire_mutex(self) -> bool:
        """Create the named mutex; fail when it already existed."""
        import win32api
        import win32event
        import winerror

        handle = win32event.CreateMutex(None, False, self._mutex_name)  # pyright: ignore[reportArgumentType]
        if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
            win32api.CloseHandle(handle)  # pyright: ignore[reportArgumentType]
            return False
        self._mutex = handle
        return True

    def _acquire_file(self) -> bool:
        """Create the lock file exclusively, replacing a stale one."""
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # A second attempt follows the removal of a stale file.
        for _ in range(2):
            try:
                fd = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if _owner_alive(self._path):
                    return False
                self._path.unlink(missing_ok=True)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(str(os.getpid()))
            return True
        return False


def write_instance(path: Path, info: InstanceInfo) -> None:
    """Write the instance file atomically as UTF-8 JSON.

    Parameters
    ----------
    path : Path
        Instance file; its folder is created when missing.
    info : InstanceInfo
        What to record.
    """
    # Write beside the target and swap it in so readers never see half a file.
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(asdict(info), handle)
        Path(tmp_name).replace(path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def read_instance(path: Path) -> InstanceInfo | None:
    """Read the instance file.

    Parameters
    ----------
    path : Path
        Instance file.

    Returns
    -------
    InstanceInfo or None
        The recorded instance, or None when the file is missing or invalid.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return InstanceInfo(
            pid=int(data["pid"]),
            port=int(data["port"]),
            secret=str(data["secret"]),
            version=str(data["version"]),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def clear_instance(path: Path, pid: int) -> None:
    """Remove the instance file when it belongs to process ``pid``.

    Parameters
    ----------
    path : Path
        Instance file.
    pid : int
        Process id that must match the recorded one.
    """
    info = read_instance(path)
    if info is not None and info.pid == pid:
        path.unlink(missing_ok=True)


def request_login_url(info: InstanceInfo, *, timeout: float = 3.0) -> str:
    """Ask a running instance for a fresh one-time login URL.

    Parameters
    ----------
    info : InstanceInfo
        The instance to ask.
    timeout : float
        Seconds to wait for the answer.

    Returns
    -------
    str
        URL that signs a browser in to the manager.

    Raises
    ------
    ConnectionError
        If the instance does not answer with a login URL.
    """
    request = urllib.request.Request(
        f"http://127.0.0.1:{info.port}/api/internal/login-code",
        data=b"",
        method="POST",
        headers={"X-Word-Session-Secret": info.secret},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return str(json.loads(response.read().decode("utf-8"))["url"])
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError) as exc:
        raise ConnectionError(f"instance on port {info.port} did not answer: {exc}") from exc


def _owner_alive(lock_path: Path) -> bool:
    """Return whether the pid recorded in a lock file is a running process."""
    try:
        pid = int(lock_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return _pid_alive(pid)


def _pid_alive(pid: int) -> bool:
    """Return whether a process with this id is running."""
    if pid <= 0:
        return False

    # On Windows os.kill would terminate the process, so ask the kernel.
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # pyright: ignore[reportAttributeAccessIssue]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
