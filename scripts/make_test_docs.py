r"""Create sample ``.docx`` files for manual and automated Word Session tests.

Run ``python scripts/make_test_docs.py [DIR]`` (default
``the temp folder, subfolder word-session-docs``). A separate invisible Word process writes
``alpha.docx``, ``beta.docx``, ``gamma.docx`` and ``with space é.docx``, each
about ten pages of numbered paragraphs, then quits. Import ``make_docs`` to
reuse the function from tests.
"""

import contextlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

DOC_NAMES = ("alpha.docx", "beta.docx", "gamma.docx", "with space é.docx")
PARAGRAPHS = 450


def word_pid(app: Any) -> int | None:
    """Return the process id of a Word application, or None when unknown."""
    try:
        import win32process

        return int(win32process.GetWindowThreadProcessId(int(app.Hwnd))[1])
    except Exception:
        return None


def wait_for_exit(pid: int | None, timeout: float = 30.0) -> None:
    """Wait until process ``pid`` has exited (a slow Word shutdown can otherwise
    be reused by the next ``DispatchEx`` and break it)."""
    if pid is None:
        return
    try:
        import win32api
        import win32con
        import win32event

        handle = win32api.OpenProcess(win32con.SYNCHRONIZE, False, pid)
    except Exception:
        return  # already gone
    try:
        win32event.WaitForSingleObject(handle, int(timeout * 1000))
    finally:
        win32api.CloseHandle(handle)


def default_dir() -> Path:
    """Return the default output folder under the temporary directory."""
    return Path(os.environ.get("TEMP", tempfile.gettempdir())) / "word-session-docs"


def make_docs(directory: Path, *, paragraphs: int = PARAGRAPHS) -> list[Path]:
    """Create the sample documents in ``directory`` with a private invisible Word.

    Parameters
    ----------
    directory : Path
        Output folder; created when missing.
    paragraphs : int
        Numbered paragraphs per document (450 is about ten pages).

    Returns
    -------
    list of Path
        The created files, in the order of ``DOC_NAMES``.

    Notes
    -----
    The calling thread must have COM initialised. The private Word process is
    always quit, so the user's Word is never touched.
    """
    import win32com.client
    import win32com.client.dynamic

    directory.mkdir(parents=True, exist_ok=True)
    raw = win32com.client.DispatchEx("Word.Application")
    app: Any = win32com.client.dynamic.Dispatch(raw._oleobj_)
    created: list[Path] = []
    pid = word_pid(app)
    try:
        app.Visible = False
        app.DisplayAlerts = 0
        for name in DOC_NAMES:
            path = directory / name
            path.unlink(missing_ok=True)
            document = app.Documents.Add()
            document.Content.Text = "\r".join(
                f"{name} paragraph number {i} with some filler text." for i in range(paragraphs)
            )
            document.SaveAs2(str(path))
            document.Close(0)
            created.append(path)
    finally:
        with contextlib.suppress(Exception):
            app.Quit(0)
        wait_for_exit(pid)
    return created


def main(argv: list[str]) -> int:
    """Create the documents in the folder given in ``argv`` and print it."""
    import pythoncom

    directory = Path(argv[0]) if argv else default_dir()
    pythoncom.CoInitialize()
    try:
        make_docs(directory)
    finally:
        pythoncom.CoUninitialize()
    print(directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
