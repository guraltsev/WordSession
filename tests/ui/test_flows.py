"""Browser smoke tests for the main Word Session UI flows (demo backend)."""

from collections.abc import Callable

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.ui.conftest import ServerPair, login

pytestmark = pytest.mark.ui


def save_session(page: Page, name: str) -> None:
    """Save the current demo session under ``name`` from the sessions list."""
    page.get_by_label("Session name (optional)").fill(name)
    page.get_by_role("button", name="Save current session").click()
    expect(page.get_by_role("link", name=name)).to_be_visible()


def open_detail(page: Page, name: str) -> None:
    """Open the detail page of the session called ``name``."""
    page.get_by_role("link", name=name).click()
    expect(page.get_by_role("heading", name=name, level=2)).to_be_visible()


def rename(page: Page, new_name: str) -> None:
    """Rename the session on the detail page."""
    page.get_by_role("button", name="Rename").click()
    page.get_by_label("Session name").fill(new_name)
    page.get_by_role("button", name="Save name").click()


def test_save_session_appears_in_table(logged_in_page: Page) -> None:
    page = logged_in_page
    save_session(page, "Alpha")
    row = page.get_by_role("row").filter(has_text="Alpha")
    expect(row).to_contain_text("manual")
    expect(row).to_contain_text("3")


def test_rename_persists_after_reload(logged_in_page: Page) -> None:
    page = logged_in_page
    save_session(page, "Before")
    open_detail(page, "Before")
    rename(page, "After")
    expect(page.get_by_role("heading", name="After", level=2)).to_be_visible()
    page.reload()
    expect(page.get_by_role("heading", name="After", level=2)).to_be_visible()


def test_pin_toggle(logged_in_page: Page) -> None:
    page = logged_in_page
    save_session(page, "Pinme")
    open_detail(page, "Pinme")
    page.get_by_role("button", name="Pin", exact=True).click()
    pinned = page.get_by_role("button", name="Pinned", exact=True)
    expect(pinned).to_have_attribute("aria-pressed", "true")
    pinned.click()
    expect(page.get_by_role("button", name="Pin", exact=True)).to_have_attribute(
        "aria-pressed", "false"
    )


def test_partial_restore_report(logged_in_page: Page) -> None:
    page = logged_in_page
    save_session(page, "Restoreme")
    open_detail(page, "Restoreme")
    page.get_by_label(r"Select C:\Demo\todo.docx").uncheck()
    page.get_by_role("button", name="Restore selected").click()
    panel = page.locator(".panel").filter(has=page.get_by_role("heading", name="Restore"))
    expect(panel.get_by_text("Restore finished")).to_be_visible()
    expect(panel.get_by_role("row")).to_have_count(3)  # header + two documents
    expect(panel).to_contain_text(r"C:\Demo\thesis.docx")
    expect(panel).to_contain_text(r"C:\Demo\notes.docx")
    expect(panel).not_to_contain_text("todo.docx")
    statuses = panel.locator("tbody tr td:first-child").all_inner_texts()
    assert len(statuses) == 2
    assert all(s.strip() in {"opened", "already_open"} for s in statuses)


def test_save_in_one_page_appears_in_other(two_pages: Callable[[], tuple[Page, Page]]) -> None:
    page1, page2 = two_pages()
    save_session(page1, "Shared")
    expect(page2.get_by_role("link", name="Shared")).to_be_visible(timeout=3000)


def test_edit_conflict_toast(two_pages: Callable[[], tuple[Page, Page]]) -> None:
    page1, page2 = two_pages()
    save_session(page1, "Conflict")
    expect(page2.get_by_role("link", name="Conflict")).to_be_visible(timeout=3000)
    open_detail(page1, "Conflict")
    open_detail(page2, "Conflict")
    # Page 2 starts editing first, so it holds a stale revision after page 1 renames.
    page2.get_by_role("button", name="Rename").click()
    page2.get_by_label("Session name").fill("From two")
    rename(page1, "From one")
    expect(page1.get_by_role("heading", name="From one", level=2)).to_be_visible()
    page2.get_by_role("button", name="Save name").click()
    expect(page2.get_by_text("changed in another tab")).to_be_visible()


def test_no_cookie_shows_not_signed_in(ui_server: ServerPair, browser: Browser) -> None:
    handle, _ = ui_server
    context = browser.new_context()
    try:
        page = context.new_page()
        page.goto(handle.url + "/")
        expect(page.get_by_role("heading", name="Not signed in")).to_be_visible()
    finally:
        context.close()


def test_stopping_server_shows_banner(stoppable_server: ServerPair, browser: Browser) -> None:
    handle, _ = stoppable_server
    context = browser.new_context()
    try:
        page = login(context, handle)
        expect(page.locator("#word-status-text")).to_contain_text("running")
        handle.stop()
        expect(page.get_by_text("Word Session is not running")).to_be_visible(timeout=10000)
    finally:
        context.close()
