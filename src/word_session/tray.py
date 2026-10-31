"""Notification-area (tray) icon and menu for the Word Session application.

Call ``build_icon(app, service)`` to get a ``pystray.Icon`` whose menu saves
and restores sessions, opens the manager or the help page and toggles
autosave and start at login. Menu actions run on background threads so the tray never blocks, and
the icon shows whether it is idle, working or warning about a failure.
"""

import importlib.resources
import logging
import os
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pystray
from PIL import Image

from word_session.config import app_paths, save_settings
from word_session.events import Event
from word_session.model import Session
from word_session.service import SessionService

if TYPE_CHECKING:
    from word_session.app import App

_log = logging.getLogger(__name__)

_RECENT_LIMIT = 8  # sessions listed in the "Recent sessions" submenu


def build_icon(app: "App", service: SessionService) -> Any:
    """Create the tray icon, its menu and the event subscriptions.

    Parameters
    ----------
    app : App
        Application whose ``open_manager``, ``open_help``, ``quit`` and
        ``autostart`` the menu uses.
    service : SessionService
        Service the menu items call; its ``events`` keep the icon current.

    Returns
    -------
    pystray.Icon
        The icon, not yet running. Its ``ws_state`` attribute is a callable
        returning ``"idle"``, ``"working"`` or ``"warning"``.
    """
    state = _IconState()

    # ---- notifications and state ----

    def notify(message: str, title: str = "Word Session") -> None:
        """Show a balloon notification, ignoring platform failures."""
        try:
            icon.notify(message, title)
        except Exception:
            _log.warning("tray notification failed: %s", message, exc_info=True)

    def refresh() -> None:
        """Show the image of the current state."""
        icon.icon = _load_image(state.current())

    # ---- menu actions (each runs on a background thread) ----

    def run_tracked(action: Callable[[], None]) -> None:
        """Run ``action`` with the working icon, reporting failures as a warning."""
        state.begin()
        refresh()
        try:
            action()
        except Exception as exc:
            _log.warning("tray action failed: %s", exc, exc_info=True)
            state.warn()
            notify(str(exc) or type(exc).__name__, "Word Session error")
        finally:
            state.end()
            refresh()

    def save_now() -> None:
        """Capture the open documents and say what happened."""
        result = service.capture()
        if result.path is None:
            notify("Word has no open documents; nothing saved")
            return
        state.clear_warning()
        count = len(result.session.documents)
        text = f"Saved {count} {'document' if count == 1 else 'documents'}"
        if result.warnings:
            text += "\n" + "\n".join(result.warnings)
        notify(text)

    def restore(selector: str) -> None:
        """Restore a session and summarise failures."""
        report = service.restore(selector)
        state.clear_warning()
        failed = [r for r in report.results if r.status in ("missing", "locked", "failed")]
        if failed:
            lines = [
                f"{r.path}: {r.status}" + (f" ({r.message})" if r.message else "") for r in failed
            ]
            notify(
                f"Restored {len(report.results) - len(failed)}, failed {len(failed)}\n"
                + "\n".join(lines)
            )
        else:
            notify(f"Restored {len(report.results)} documents")

    def restore_callback(session_id: str) -> Callable[[Any, Any], None]:
        """Build the menu callback that restores one session."""
        return background(lambda: restore(session_id))

    def recent_items() -> tuple[pystray.MenuItem, ...]:
        """Build one menu item per recent session, pinned first."""
        sessions = recent_sessions(service)
        if not sessions:
            return (pystray.MenuItem("(no sessions yet)", None, enabled=False),)
        return tuple(
            pystray.MenuItem(
                _session_label(s),
                restore_callback(s.id),
            )
            for s in sessions
        )

    def toggle_autosave() -> None:
        """Flip and persist ``settings.autosave.enabled``."""
        service.settings.autosave.enabled = not service.settings.autosave.enabled
        save_settings(service.settings)
        app.trigger_autosave()

    def toggle_start_at_login() -> None:
        """Flip the setting and make the autostart registration match it."""
        wanted = not service.settings.ui.start_at_login
        try:
            if wanted:
                app.autostart.enable(app.autostart.app_command())
            else:
                app.autostart.disable()
        except Exception as exc:
            _log.warning("changing start at login failed: %s", exc, exc_info=True)
            notify(f"Could not change start at login: {exc}")
            return
        service.settings.ui.start_at_login = wanted
        save_settings(service.settings)

    def open_path(path_name: str) -> None:
        """Open the sessions folder or the log file with the shell."""
        paths = app_paths()
        target = (
            service.store.root if path_name == "sessions" else paths.log_dir / "word-session.log"
        )
        startfile = getattr(os, "startfile", None)
        if startfile is None or not target.exists():
            notify(f"Cannot open {target}")
            return
        startfile(target)

    def background(action: Callable[[], None]) -> Callable[[Any, Any], None]:
        """Wrap ``action`` as a menu callback that runs tracked on a thread."""
        return lambda icon_, item_: _spawn(lambda: run_tracked(action))

    # ---- menu ----

    menu = pystray.Menu(
        pystray.MenuItem("Save session now", background(save_now)),
        pystray.MenuItem("Restore latest session", background(lambda: restore("latest"))),
        pystray.MenuItem("Recent sessions", pystray.Menu(recent_items)),
        pystray.MenuItem("Open manager…", lambda icon_, item_: app.open_manager(), default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "Autosave",
            lambda icon_, item_: toggle_autosave(),
            checked=lambda item_: service.settings.autosave.enabled,
        ),
        pystray.MenuItem(
            "Start at login",
            lambda icon_, item_: toggle_start_at_login(),
            checked=lambda item_: service.settings.ui.start_at_login,
        ),
        pystray.MenuItem("Open sessions folder", lambda icon_, item_: open_path("sessions")),
        pystray.MenuItem("Open log", lambda icon_, item_: open_path("log")),
        pystray.MenuItem("Help", lambda icon_, item_: app.open_help()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", lambda icon_, item_: app.quit()),
    )
    icon = pystray.Icon("word-session", _load_image("idle"), "Word Session", menu)

    # ---- service events keep the menu and icon current ----

    def on_event(event: Event) -> None:
        """React to a service event on the thread that published it."""
        kind = event.get("type")
        if kind == "autosave_failed":
            state.warn()
            refresh()
            notify(str(event.get("message", "Autosave failed")), "Autosave failed")
        elif kind == "session_saved":
            if event.get("kind") == "auto":
                state.clear_warning()
                refresh()
        if kind in ("session_saved", "session_updated", "session_deleted"):
            icon.update_menu()

    service.events.subscribe(on_event)
    icon.ws_state = state.current  # pyright: ignore[reportAttributeAccessIssue]
    return icon


def recent_sessions(service: SessionService) -> list[Session]:
    """Return up to eight sessions for the tray: pinned first, then newest.

    Parameters
    ----------
    service : SessionService
        Service to list from.

    Returns
    -------
    list of Session
        Pinned sessions (newest first) followed by the others (newest first).
    """
    # ``list_sessions`` is newest first and ``sorted`` is stable.
    sessions = sorted(service.list_sessions(), key=lambda s: not s.pinned)
    return sessions[:_RECENT_LIMIT]


# ---- helpers ----------------------------------------------------------------


class _IconState:
    """Track busy actions and the warning flag, and name the icon to show."""

    def __init__(self) -> None:
        self._busy = 0
        self._warning = False
        self._lock = threading.Lock()

    def begin(self) -> None:
        with self._lock:
            self._busy += 1

    def end(self) -> None:
        with self._lock:
            self._busy -= 1

    def warn(self) -> None:
        with self._lock:
            self._warning = True

    def clear_warning(self) -> None:
        with self._lock:
            self._warning = False

    def current(self) -> str:
        """Return ``working``, ``warning`` or ``idle``."""
        with self._lock:
            if self._busy > 0:
                return "working"
            return "warning" if self._warning else "idle"


def _session_label(session: Session) -> str:
    """Format a session for the recent list (pinned ones are starred)."""
    stamp = session.created_at.strftime("%Y-%m-%d %H:%M")
    return f"{'* ' if session.pinned else ''}{session.name} ({stamp})".replace("&", "&&")


def _load_image(state: str) -> Image.Image:
    """Load the packaged tray image for ``idle``, ``working`` or ``warning``."""
    resource = importlib.resources.files("word_session") / "assets" / f"tray-{state}.png"
    with resource.open("rb") as handle:
        image = Image.open(handle)
        image.load()
    return image


def _spawn(action: Callable[[], None]) -> None:
    """Run ``action`` on a daemon thread (tests replace this to run inline)."""
    threading.Thread(target=action, name="tray-action", daemon=True).start()
