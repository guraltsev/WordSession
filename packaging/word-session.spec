# PyInstaller spec: one onedir bundle holding a console and a windowed exe.
# Build with: uv run pyinstaller --noconfirm --clean packaging/word-session.spec
import sys
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is injected by PyInstaller
sys.path.insert(0, str(ROOT / "packaging"))

from version_info import build_version_info  # noqa: E402

SRC = ROOT / "src" / "word_session"

shared = dict(
    pathex=[str(ROOT / "src")],
    binaries=[],
    # copy_metadata keeps importlib.metadata.version("word-session") working when frozen.
    datas=[
        (str(SRC / "web" / "static"), "word_session/web/static"),
        (str(SRC / "assets"), "word_session/assets"),
        *copy_metadata("word-session"),
    ],
    hiddenimports=[
        "win32timezone",
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "pystray._win32",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "wx", "IPython", "jupyter_client", "matplotlib"],
    noarchive=False,
)

cli_analysis = Analysis([str(ROOT / "packaging" / "entry_cli.py")], **shared)  # noqa: F821
app_analysis = Analysis([str(ROOT / "packaging" / "entry_app.py")], **shared)  # noqa: F821
MERGE(  # noqa: F821
    (cli_analysis, "word-session", "word-session"),
    (app_analysis, "word-session-app", "word-session-app"),
)

icon = str(ROOT / "packaging" / "icons" / "app.ico")

cli_exe = EXE(  # noqa: F821
    PYZ(cli_analysis.pure),  # noqa: F821
    cli_analysis.scripts,
    [],
    exclude_binaries=True,
    name="word-session",
    console=True,
    icon=icon,
    upx=False,
    version=build_version_info("word-session.exe", "Word Session command line"),
)
app_exe = EXE(  # noqa: F821
    PYZ(app_analysis.pure),  # noqa: F821
    app_analysis.scripts,
    [],
    exclude_binaries=True,
    name="word-session-app",
    console=False,
    icon=icon,
    upx=False,
    version=build_version_info("word-session-app.exe", "Word Session tray application"),
)

COLLECT(  # noqa: F821
    cli_exe,
    cli_analysis.binaries,
    cli_analysis.datas,
    app_exe,
    app_analysis.binaries,
    app_analysis.datas,
    strip=False,
    upx=False,
    name="WordSession",
)
