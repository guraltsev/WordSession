"""The long-running Word Session application: tray icon, worker and web server.

``App(...).run()`` starts the single per-user instance (or, when one is already
running, asks it to open the manager in the browser) and blocks until the user
quits from the tray. ``word-session-cli app`` and the windowed launcher run it.
"""

import logging
import os
import sys
import threading
import webbrowser
from types import ModuleType

from word_session import __version__, autostart
from word_session.autosave import Autosaver
from word_session.config import app_paths, load_settings
from word_session.instance import (
    InstanceInfo,
    InstanceLock,
    clear_instance,
    read_instance,
    request_login_url,
    write_instance,
)
from word_session.logging_setup import configure_logging
from word_session.service import SessionService, open_service
from word_session.web.server import ServerHandle

_log = logging.getLogger(__name__)


class App:
    """Own the service, the local server and the tray icon of one user session.

    Parameters
    ----------
    fake : bool
        Use the in-memory demo Word instead of the real one.
    open_browser : bool
        Open the manager once the tray icon is up (Start menu launch).
    lock : InstanceLock or None
        Single-instance lock; defaults to the per-user named mutex.
    autostart_module : ModuleType or None
        Module providing ``is_enabled``, ``enable``, ``disable`` and
        ``app_command``; defaults to ``word_session.autostart`` (tests pass a
        fake so the real registry is never touched).

    Attributes
    ----------
    autostart : ModuleType
        The start-at-login module in use.
    handle : ServerHandle or None
        The running server, available while ``run`` is active.
    """

    def __init__(
        self,
        *,
        fake: bool = False,
        open_browser: bool = False,
        lock: InstanceLock | None = None,
        autostart_module: ModuleType | None = None,
    ) -> None:
        self._fake = fake
        self._open_browser = open_browser
        self._lock = lock
        self.autostart: ModuleType = autostart_module if autostart_module is not None else autostart
        self.handle: ServerHandle | None = None
        self._icon: object | None = None
        self._autosaver: Autosaver | None = None
        self._quit_requested = threading.Event()

    def run(self) -> int:
        """Run the application until the user quits.

        Returns
        -------
        int
            0 on a normal exit (including handing over to a running
            instance), 1 when another instance is running but does not answer.
        """
        paths = app_paths()

        # Only one instance per user: hand over to the running one instead.
        lock = self._lock if self._lock is not None else InstanceLock()
        if not lock.acquire():
            return self._hand_over()

        service: SessionService | None = None
        try:
            # Start logging, the Word worker and the local server.
            configure_logging(paths.log_dir, console_level=None)
            settings = load_settings(paths.config_file)
            service = open_service(settings=settings, fake=self._fake)
            from word_session.web.server import start_server

            self.handle = start_server(
                service, on_shutdown=self.quit, on_settings_changed=self.trigger_autosave
            )

            # Publish how to reach this instance only once the server answers.
            write_instance(
                paths.instance_file,
                InstanceInfo(
                    pid=os.getpid(),
                    port=self.handle.port,
                    secret=self.handle.auth.instance_secret,
                    version=__version__,
                ),
            )
            self._apply_start_at_login(service)

            # Autosave starts after the server and stops first on quit.
            self._autosaver = Autosaver(service)
            self._autosaver.start()

            # The tray owns the main thread until Quit (or the shutdown route).
            from word_session import tray

            icon = tray.build_icon(self, service)
            self._icon = icon
            icon.run(setup=self._on_icon_ready)
            return 0
        finally:
            # Tear down in reverse order of startup.
            self._icon = None
            if self._autosaver is not None:
                self._autosaver.stop()
                self._autosaver = None
            if self.handle is not None:
                self.handle.stop()
            if service is not None:
                service.close()
            clear_instance(paths.instance_file, os.getpid())
            lock.release()

    def open_manager(self) -> None:
        """Open the manager in the default browser with a fresh login code.

        Notes
        -----
        Other open tabs stay signed in. Does nothing when the server is not
        running.
        """
        if self.handle is None:
            return
        url = f"{self.handle.url}/login?code={self.handle.auth.mint_login_code()}"
        webbrowser.open(url)

    def open_help(self) -> None:
        """Open the user guide served by the local server in the default browser.

        Notes
        -----
        The help page needs no login. Does nothing when the server is not
        running.
        """
        if self.handle is None:
            return
        webbrowser.open(f"{self.handle.url}/help.html")

    def trigger_autosave(self) -> None:
        """Wake the autosaver so new autosave settings apply immediately."""
        if self._autosaver is not None:
            self._autosaver.trigger()

    def quit(self) -> None:
        """Ask ``run`` to return by stopping the tray icon."""
        self._quit_requested.set()
        icon = self._icon
        if icon is not None:
            icon.stop()  # pyright: ignore[reportAttributeAccessIssue]

    # ---- internals ----

    def _on_icon_ready(self, icon: object) -> None:
        """Show the icon, then honour a pending quit or open request."""
        icon.visible = True  # pyright: ignore[reportAttributeAccessIssue]
        if self._quit_requested.is_set():
            icon.stop()  # pyright: ignore[reportAttributeAccessIssue]
            return
        if self._open_browser:
            self.open_manager()

    def _hand_over(self) -> int:
        """Ask the running instance to open the manager; report failure."""
        info = read_instance(app_paths().instance_file)
        try:
            if info is None:
                raise ConnectionError("no instance file")
            webbrowser.open(request_login_url(info))
        except ConnectionError:
            _log.warning("running instance does not answer", exc_info=True)
            _message_box("Word Session is already running but not responding")
            return 1
        return 0

    def _apply_start_at_login(self, service: SessionService) -> None:
        """Make the autostart registration match ``settings.ui.start_at_login``."""
        wanted = service.settings.ui.start_at_login
        try:
            if wanted != self.autostart.is_enabled():
                if wanted:
                    self.autostart.enable(self.autostart.app_command())
                else:
                    self.autostart.disable()
        except Exception:
            _log.warning("could not apply start at login", exc_info=True)


def _message_box(text: str) -> None:
    """Show a Windows message box; fall back to stderr elsewhere."""
    try:
        import ctypes

        windll = getattr(ctypes, "windll", None)
        if windll is None:
            raise OSError("no message boxes on this platform")
        windll.user32.MessageBoxW(None, text, "Word Session", 0x10)
    except Exception:
        print(text, file=sys.stderr)
