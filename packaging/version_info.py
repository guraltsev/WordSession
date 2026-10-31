"""Generate the Windows version resource for the PyInstaller executables."""

from __future__ import annotations

import re
from importlib.metadata import version

from PyInstaller.utils.win32.versioninfo import (  # type: ignore[import-untyped]
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)


def _numeric(text: str) -> tuple[int, int, int, int]:
    """Return up to four leading integers of a version string, padded with zeros."""
    numbers = [int(part) for part in re.findall(r"\d+", text)[:4]]
    numbers += [0] * (4 - len(numbers))
    return (numbers[0], numbers[1], numbers[2], numbers[3])


def build_version_info(name: str, description: str) -> VSVersionInfo:
    """Build the version resource for one executable.

    Parameters
    ----------
    name : str
        Original file name, for example ``word-session.exe``.
    description : str
        File description shown in the Windows properties dialog.

    Returns
    -------
    VSVersionInfo
        Resource to pass as ``version=`` to ``EXE``.
    """
    text = version("word-session")
    numbers = _numeric(text)
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers, mask=0x3F, flags=0x0, OS=0x40004),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040904B0",
                        [
                            StringStruct("CompanyName", "Word Session"),
                            StringStruct("FileDescription", description),
                            StringStruct("FileVersion", text),
                            StringStruct("InternalName", name),
                            StringStruct("OriginalFilename", name),
                            StringStruct("ProductName", "Word Session"),
                            StringStruct("ProductVersion", text),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )
