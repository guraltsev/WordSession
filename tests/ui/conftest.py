"""Fixtures for the browser UI tests: a demo server and logged-in Playwright pages."""

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, BrowserContext, Page

from word_session.service import SessionService, open_service
from word_session.web.server import ServerHandle, start_server

ServerPair = tuple[ServerHandle, SessionService]


def _serve(home: Path) -> Iterator[ServerPair]:
    """Start a demo service and server under ``home``; stop both afterwards."""
    previous = os.environ.get("WORD_SESSION_HOME")
    os.environ["WORD_SESSION_HOME"] = str(home)
    service = open_service(fake=True)
    handle = start_server(service, port=0)
    try:
        yield handle, service
    finally:
        handle.stop()
        service.close()
        if previous is None:
            os.environ.pop("WORD_SESSION_HOME", None)
        else:
            os.environ["WORD_SESSION_HOME"] = previous


@pytest.fixture(scope="session")
def ui_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ServerPair]:
    """Serve the demo backend once for the whole run."""
    yield from _serve(tmp_path_factory.mktemp("ui-home"))


@pytest.fixture
def stoppable_server(tmp_path: Path) -> Iterator[ServerPair]:
    """Serve a private demo backend that a test may stop itself."""
    yield from _serve(tmp_path / "stop-home")


@pytest.fixture
def clean_store(ui_server: ServerPair) -> None:
    """Delete every session before a test so tests stay independent."""
    _, service = ui_server
    for session in service.list_sessions():
        service.delete(session.id, purge=True)


def login(context: BrowserContext, handle: ServerHandle) -> Page:
    """Open a page in ``context`` signed in with a fresh single-use login code."""
    page = context.new_page()
    page.goto(f"{handle.url}/login?code={handle.auth.mint_login_code()}")
    page.wait_for_selector("h2:has-text('Sessions')")
    return page


@pytest.fixture
def logged_in_page(ui_server: ServerPair, clean_store: None, page: Page) -> Page:
    """Return ``page`` signed in to the shared server and showing the sessions list."""
    handle, _ = ui_server
    page.goto(f"{handle.url}/login?code={handle.auth.mint_login_code()}")
    page.wait_for_selector("h2:has-text('Sessions')")
    return page


@pytest.fixture
def two_pages(
    ui_server: ServerPair, clean_store: None, browser: Browser
) -> Iterator[Callable[[], tuple[Page, Page]]]:
    """Return a factory for two pages with separate logins; contexts close at teardown."""
    handle, _ = ui_server
    contexts: list[BrowserContext] = []

    def make() -> tuple[Page, Page]:
        pages: list[Page] = []
        for _ in range(2):
            context = browser.new_context()
            contexts.append(context)
            pages.append(login(context, handle))
        return pages[0], pages[1]

    yield make
    for context in contexts:
        context.close()
