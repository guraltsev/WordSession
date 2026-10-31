"""Tests for the application lifecycle and the tray menu (no real tray, registry or Word)."""

import threading
import webbrowser
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pystray
import pytest

from word_session import app as app_module
from word_session import tray
from word_session.app import App
from word_session.config import Settings, load_settings, save_settings
from word_session.instance import InstanceLock, read_instance
from word_session.service import SessionService


class FakeIcon:
    """Stand-in for ``pystray.Icon`` whose ``run`` calls a hook and returns."""

    hook: Callable[["FakeIcon"], object] | None = None

    def __init__(self, name: str, icon: Any, title: str, menu: Any) -> None:
        self.name = name
        self.icon = icon
        self.title = title
        self.menu = menu
        self.visible = False
        self.stopped = False
        self.menu_updates = 0
        self.notifications: list[tuple[str, str]] = []

    def run(self, setup: Callable[["FakeIcon"], None] | None = None) -> None:
        if setup is not None:
            setup(self)
        if FakeIcon.hook is not None:
            FakeIcon.hook(self)

    def stop(self) -> None:
        self.stopped = True

    def update_menu(self) -> None:
        self.menu_updates += 1

    def notify(self, message: str, title: str = "") -> None:
        self.notifications.append((title, message))


class FakeAutostart:
    """Records autostart calls instead of touching the registry."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.calls: list[str] = []

    def is_enabled(self) -> bool:
        return self.enabled

    def enable(self, command: str) -> None:
        self.calls.append(f"enable {command}")
        self.enabled = True

    def disable(self) -> None:
        self.calls.append("disable")
        self.enabled = False

    def app_command(self) -> str:
        return "fake-app-command"


@pytest.fixture
def fake_icon(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[FakeIcon]]:
    FakeIcon.hook = None
    monkeypatch.setattr(pystray, "Icon", FakeIcon)
    yield FakeIcon
    FakeIcon.hook = None


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    urls: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda url: urls.append(url) or True)
    return urls


def make_app(
    isolated_home: Path, autostart: FakeAutostart | None = None, **kwargs: Any
) -> tuple[App, FakeAutostart]:
    autostart = autostart if autostart is not None else FakeAutostart()
    lock = InstanceLock(isolated_home / "instance.lock", use_mutex=False)
    return App(fake=True, lock=lock, autostart_module=autostart, **kwargs), autostart  # pyright: ignore[reportArgumentType]


# ---- App.run ---------------------------------------------------------------


def test_run_starts_server_writes_instance_and_cleans_up(
    isolated_home: Path, fake_icon: type[FakeIcon], opened: list[str]
) -> None:
    app, _ = make_app(isolated_home)
    seen: dict[str, Any] = {}

    def hook(icon: FakeIcon) -> None:
        info = read_instance(isolated_home / "instance.json")
        seen["info"] = info
        assert info is not None
        seen["health"] = httpx.get(f"http://127.0.0.1:{info.port}/api/health").json()
        seen["lock_exists"] = (isolated_home / "instance.lock").exists()
        seen["visible"] = icon.visible

    fake_icon.hook = hook
    assert app.run() == 0

    assert seen["health"]["ok"] is True
    assert seen["info"].secret
    assert seen["lock_exists"]
    assert seen["visible"]
    assert opened == []
    assert not (isolated_home / "instance.json").exists()
    assert not (isolated_home / "instance.lock").exists()


def test_open_browser_opens_manager_when_icon_is_up(
    isolated_home: Path, fake_icon: type[FakeIcon], opened: list[str]
) -> None:
    app, _ = make_app(isolated_home, open_browser=True)
    assert app.run() == 0
    assert len(opened) == 1
    assert "/login?code=" in opened[0]


def test_open_manager_mints_new_code_each_time(
    isolated_home: Path, fake_icon: type[FakeIcon], opened: list[str]
) -> None:
    app, _ = make_app(isolated_home)
    fake_icon.hook = lambda icon: (app.open_manager(), app.open_manager())
    app.run()
    assert len(opened) == 2
    assert opened[0] != opened[1]


def test_open_manager_without_server_does_nothing(isolated_home: Path, opened: list[str]) -> None:
    app, _ = make_app(isolated_home)
    app.open_manager()
    assert opened == []


def test_open_help_opens_help_page_without_login(
    isolated_home: Path, fake_icon: type[FakeIcon], opened: list[str]
) -> None:
    app, _ = make_app(isolated_home)
    responses: list[httpx.Response] = []

    def hook(icon: FakeIcon) -> None:
        app.open_help()
        responses.append(httpx.get(opened[0], timeout=5))  # no login cookie

    fake_icon.hook = hook
    app.run()
    assert len(opened) == 1
    assert opened[0].endswith("/help.html")
    assert "/login" not in opened[0]
    assert responses[0].status_code == 200
    assert "<title>Word Session help</title>" in responses[0].text


def test_open_help_without_server_does_nothing(isolated_home: Path, opened: list[str]) -> None:
    app, _ = make_app(isolated_home)
    app.open_help()
    assert opened == []


def test_shutdown_endpoint_quits_the_app(
    isolated_home: Path, fake_icon: type[FakeIcon], opened: list[str]
) -> None:
    app, _ = make_app(isolated_home)
    result: dict[str, Any] = {}

    def hook(icon: FakeIcon) -> None:
        info = read_instance(isolated_home / "instance.json")
        assert info is not None
        url = f"http://127.0.0.1:{info.port}/api/internal/shutdown"
        result["wrong"] = httpx.post(url, headers={"X-Word-Session-Secret": "nope"}).status_code
        result["ok"] = httpx.post(url, headers={"X-Word-Session-Secret": info.secret}).status_code
        result["stopped"] = icon.stopped

    fake_icon.hook = hook
    app.run()
    assert result == {"wrong": 401, "ok": 200, "stopped": True}


def test_second_instance_asks_the_first_to_open_the_browser(
    isolated_home: Path, fake_icon: type[FakeIcon], opened: list[str]
) -> None:
    first, _ = make_app(isolated_home)
    second, _ = make_app(isolated_home)
    codes: list[int] = []

    def hook(icon: FakeIcon) -> None:
        info = read_instance(isolated_home / "instance.json")
        assert info is not None
        codes.append(second.run())
        assert opened[0].startswith(f"http://127.0.0.1:{info.port}/login?code=")
        # The first instance is still running and still owns its files.
        assert (isolated_home / "instance.json").exists()

    fake_icon.hook = hook
    assert first.run() == 0
    assert codes == [0]
    assert len(opened) == 1


def test_second_instance_reports_unresponsive_first(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, opened: list[str]
) -> None:
    holder = InstanceLock(isolated_home / "instance.lock", use_mutex=False)
    assert holder.acquire()
    boxes: list[str] = []
    monkeypatch.setattr(app_module, "_message_box", boxes.append)
    app, _ = make_app(isolated_home)
    try:
        assert app.run() == 1
    finally:
        holder.release()
    assert boxes == ["Word Session is already running but not responding"]
    assert opened == []


def test_start_at_login_setting_is_applied(
    isolated_home: Path, fake_icon: type[FakeIcon], opened: list[str]
) -> None:
    settings = Settings()
    settings.ui.start_at_login = True
    save_settings(settings)
    app, autostart = make_app(isolated_home)
    app.run()
    assert autostart.calls == ["enable fake-app-command"]

    settings.ui.start_at_login = False
    save_settings(settings)
    app, autostart = make_app(isolated_home, FakeAutostart(enabled=True))
    app.run()
    assert autostart.calls == ["disable"]


def test_start_at_login_failure_is_not_fatal(
    isolated_home: Path, fake_icon: type[FakeIcon], opened: list[str]
) -> None:
    settings = Settings()
    settings.ui.start_at_login = True
    save_settings(settings)
    autostart = FakeAutostart()
    autostart.enable = lambda command: (_ for _ in ()).throw(OSError("denied"))  # type: ignore[method-assign]
    app, _ = make_app(isolated_home, autostart)
    assert app.run() == 0


# ---- tray ------------------------------------------------------------------


@pytest.fixture
def inline_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tray, "_spawn", lambda action: action())


class FakeApp:
    def __init__(self) -> None:
        self.autostart = FakeAutostart()
        self.opened = 0
        self.help_opened = 0
        self.quit_called = 0
        self.autosave_triggers = 0

    def trigger_autosave(self) -> None:
        self.autosave_triggers += 1

    def open_manager(self) -> None:
        self.opened += 1

    def open_help(self) -> None:
        self.help_opened += 1

    def quit(self) -> None:
        self.quit_called += 1


def build(service: SessionService) -> tuple[FakeIcon, FakeApp]:
    fake_app = FakeApp()
    icon = tray.build_icon(fake_app, service)  # pyright: ignore[reportArgumentType]
    return icon, fake_app


def item_named(menu: Any, text: str) -> Any:
    return next(i for i in menu.items if i.text == text)


@pytest.fixture
def tray_icon(
    fake_icon: type[FakeIcon], inline_spawn: None, service: SessionService
) -> tuple[FakeIcon, FakeApp]:
    return build(service)


def test_menu_layout_and_default_item(tray_icon: tuple[FakeIcon, FakeApp]) -> None:
    icon, fake_app = tray_icon
    texts = [i.text for i in icon.menu.items if i.text != "- - - -"]
    assert texts == [
        "Save session now",
        "Restore latest session",
        "Recent sessions",
        "Open manager…",
        "Autosave",
        "Start at login",
        "Open sessions folder",
        "Open log",
        "Help",
        "Quit",
    ]
    assert item_named(icon.menu, "Open manager…").default
    item_named(icon.menu, "Open manager…")(icon)
    item_named(icon.menu, "Help")(icon)
    item_named(icon.menu, "Quit")(icon)
    assert (fake_app.opened, fake_app.help_opened, fake_app.quit_called) == (1, 1, 1)
    assert icon.title == "Word Session"


def test_save_now_captures_and_notifies(
    tray_icon: tuple[FakeIcon, FakeApp], service: SessionService
) -> None:
    icon, _ = tray_icon
    item_named(icon.menu, "Save session now")(icon)
    assert len(service.list_sessions()) == 1
    assert icon.notifications[-1][1] == "Saved 2 documents"
    assert icon.ws_state() == "idle"  # pyright: ignore[reportAttributeAccessIssue]


def test_restore_latest_notifies_summary(
    tray_icon: tuple[FakeIcon, FakeApp], service: SessionService
) -> None:
    icon, _ = tray_icon
    service.capture("first")
    item_named(icon.menu, "Restore latest session")(icon)
    assert icon.notifications[-1][1] == "Restored 2 documents"


def test_restore_failure_lists_failed_documents(
    tray_icon: tuple[FakeIcon, FakeApp], service: SessionService
) -> None:
    icon, _ = tray_icon
    service.capture("first")
    service.update("first", name="first")
    session = service.list_sessions()[0]
    # A document that is not found on disk is reported as missing.
    session_path = service.store.root / f"{session.id}.json"
    session_path.write_text(
        session_path.read_text(encoding="utf-8").replace("a.docx", "missing.docx"),
        encoding="utf-8",
    )
    item_named(icon.menu, "Restore latest session")(icon)
    message = icon.notifications[-1][1]
    assert "failed 1" in message
    assert "missing.docx" in message


def test_action_error_sets_warning_state(
    tray_icon: tuple[FakeIcon, FakeApp], service: SessionService
) -> None:
    icon, _ = tray_icon
    item_named(icon.menu, "Restore latest session")(icon)  # no sessions yet
    assert icon.notifications[-1][0] == "Word Session error"
    assert icon.ws_state() == "warning"  # pyright: ignore[reportAttributeAccessIssue]

    # The next success clears the warning.
    item_named(icon.menu, "Save session now")(icon)
    assert icon.ws_state() == "idle"  # pyright: ignore[reportAttributeAccessIssue]


def test_working_state_during_action(
    tray_icon: tuple[FakeIcon, FakeApp], service: SessionService, monkeypatch: pytest.MonkeyPatch
) -> None:
    icon, _ = tray_icon
    seen: list[str] = []
    real_capture = service.capture

    def capture(*args: Any, **kwargs: Any) -> Any:
        seen.append(icon.ws_state())  # pyright: ignore[reportAttributeAccessIssue]
        return real_capture(*args, **kwargs)

    monkeypatch.setattr(service, "capture", capture)
    item_named(icon.menu, "Save session now")(icon)
    assert seen == ["working"]


def test_autosave_failure_event_sets_warning_and_next_autosave_clears(
    tray_icon: tuple[FakeIcon, FakeApp], service: SessionService
) -> None:
    icon, _ = tray_icon
    service.events.publish({"type": "autosave_failed", "message": "Word is busy"})
    assert icon.ws_state() == "warning"  # pyright: ignore[reportAttributeAccessIssue]
    assert icon.notifications[-1] == ("Autosave failed", "Word is busy")
    service.events.publish({"type": "session_saved", "session_id": "x", "kind": "auto"})
    assert icon.ws_state() == "idle"  # pyright: ignore[reportAttributeAccessIssue]


def test_recent_sessions_pinned_first_then_newest_max_eight(
    service: SessionService,
) -> None:
    ids = [service.capture(f"s{n}").session.id for n in range(10)]
    service.update(ids[1], pinned=True)
    service.update(ids[0], pinned=True)
    ordered = [s.name for s in tray.recent_sessions(service)]
    assert ordered == ["s1", "s0", "s9", "s8", "s7", "s6", "s5", "s4"]


def test_recent_submenu_restores_clicked_session_and_refreshes(
    tray_icon: tuple[FakeIcon, FakeApp], service: SessionService
) -> None:
    icon, _ = tray_icon
    recent = item_named(icon.menu, "Recent sessions")
    assert [i.text for i in recent.submenu.items] == ["(no sessions yet)"]

    first = service.capture("alpha").session
    service.capture("beta")
    assert icon.menu_updates == 2  # session_saved events refresh the menu
    items = item_named(icon.menu, "Recent sessions").submenu.items
    assert [i.text.split(" (")[0] for i in items] == ["beta", "alpha"]

    items[1](icon)
    assert icon.notifications[-1][1] == "Restored 2 documents"
    assert first.id


def test_autosave_toggle_is_checkable_and_persisted(
    tray_icon: tuple[FakeIcon, FakeApp], service: SessionService
) -> None:
    icon, _ = tray_icon
    item = item_named(icon.menu, "Autosave")
    assert item.checked is True
    item(icon)
    assert item_named(icon.menu, "Autosave").checked is False
    assert load_settings().autosave.enabled is False
    item(icon)
    assert load_settings().autosave.enabled is True


def test_start_at_login_toggle_updates_autostart_and_settings(
    tray_icon: tuple[FakeIcon, FakeApp], service: SessionService
) -> None:
    icon, fake_app = tray_icon
    item = item_named(icon.menu, "Start at login")
    assert item.checked is False
    item(icon)
    assert fake_app.autostart.calls == ["enable fake-app-command"]
    assert load_settings().ui.start_at_login is True
    assert item_named(icon.menu, "Start at login").checked is True
    item(icon)
    assert fake_app.autostart.calls[-1] == "disable"
    assert load_settings().ui.start_at_login is False


def test_start_at_login_failure_keeps_setting(
    tray_icon: tuple[FakeIcon, FakeApp], service: SessionService
) -> None:
    icon, fake_app = tray_icon

    def boom(command: str) -> None:
        raise NotImplementedError("not here")

    fake_app.autostart.enable = boom  # type: ignore[method-assign]
    item_named(icon.menu, "Start at login")(icon)
    assert service.settings.ui.start_at_login is False
    assert "Could not change start at login" in icon.notifications[-1][1]


def test_open_folder_and_log_use_the_shell(
    tray_icon: tuple[FakeIcon, FakeApp],
    service: SessionService,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    icon, _ = tray_icon
    started: list[Path] = []
    monkeypatch.setattr("os.startfile", started.append, raising=False)
    service.store.root.mkdir(parents=True, exist_ok=True)
    item_named(icon.menu, "Open sessions folder")(icon)
    assert started == [service.store.root]

    # A log file that does not exist yet is reported instead of opened.
    item_named(icon.menu, "Open log")(icon)
    assert started == [service.store.root]
    assert "Cannot open" in icon.notifications[-1][1]
    (isolated_home / "logs").mkdir()
    (isolated_home / "logs" / "word-session.log").write_text("x", encoding="utf-8")
    item_named(icon.menu, "Open log")(icon)
    assert started[-1] == isolated_home / "logs" / "word-session.log"


def test_icon_images_load_for_every_state() -> None:
    for state in ("idle", "working", "warning"):
        assert tray._load_image(state).size == (64, 64)  # pyright: ignore[reportPrivateUsage]


def test_spawn_runs_action_on_another_thread() -> None:
    done = threading.Event()
    names: list[str] = []

    def action() -> None:
        names.append(threading.current_thread().name)
        done.set()

    tray._spawn(action)  # pyright: ignore[reportPrivateUsage]
    assert done.wait(5)
    assert names == ["tray-action"]
