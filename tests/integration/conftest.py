"""Fixtures for tests that drive real Word through isolated hidden processes."""

import contextlib
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from word_session.word.com import ComWordBackend

DocxFactory = Callable[..., Path]


@pytest.fixture
def com_initialised() -> Iterator[None]:
    """Initialise COM on the test thread and uninitialise it at teardown."""
    if sys.platform != "win32":
        pytest.skip("COM needs Windows")
    import pythoncom

    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


@pytest.fixture
def word(com_initialised: None) -> Iterator[ComWordBackend]:
    """Yield a connected backend on a private invisible Word, quit at teardown."""
    backend = ComWordBackend(isolated=True)
    try:
        backend.connect(start_if_needed=True)
        yield backend
    finally:
        backend.disconnect()


@pytest.fixture
def docx_factory(com_initialised: None, tmp_path: Path) -> Iterator[DocxFactory]:
    """Yield a function creating multi-page ``.docx`` files with a separate Word."""
    import win32com.client
    import win32com.client.dynamic

    apps: list[Any] = []

    def make(name: str = "doc.docx", paragraphs: int = 200) -> Path:
        # Start the helper Word lazily, once per test.
        if not apps:
            raw = win32com.client.DispatchEx("Word.Application")
            app = win32com.client.dynamic.Dispatch(raw._oleobj_)
            app.Visible = False
            app.DisplayAlerts = 0
            apps.append(app)
        app = apps[0]

        # Fill a new document with numbered paragraphs and save it.
        path = tmp_path / name
        document = app.Documents.Add()
        document.Content.Text = "\r".join(
            f"Paragraph number {i} with some filler text." for i in range(paragraphs)
        )
        document.SaveAs2(str(path))
        document.Close(0)
        return path

    try:
        yield make
    finally:
        for app in apps:
            with contextlib.suppress(Exception):
                app.Quit(0)
