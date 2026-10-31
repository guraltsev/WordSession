"""Save and restore Microsoft Word sessions.

The package exposes ``__version__``, the installed distribution version, which
is ``"0.0.0"`` when the package metadata is unavailable.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("word-session")
except PackageNotFoundError:
    # Running from a source tree without installed metadata.
    __version__ = "0.0.0"

__all__ = ["__version__"]
