"""Single-use login codes and session tokens for the local web manager.

``Auth`` mints short-lived codes that a browser exchanges for a session token
(stored in a cookie). The per-process ``instance_secret`` authorises the
processes that mint codes. State lives in memory only.
"""

import secrets
import threading
import time
from collections.abc import Callable


class Auth:
    """Issue login codes and validate the session tokens they are exchanged for.

    Parameters
    ----------
    code_ttl : float
        Seconds a login code stays valid.
    clock : Callable[[], float]
        Monotonic time source in seconds; injectable for tests.

    Attributes
    ----------
    instance_secret : str
        Random secret that authorises minting login codes over HTTP.

    Notes
    -----
    Codes are single use. Session tokens never expire while the process runs,
    and any number of them may be valid at once (one per logged-in tab).
    """

    def __init__(
        self, *, code_ttl: float = 60.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.instance_secret: str = secrets.token_urlsafe(32)
        self._code_ttl = code_ttl
        self._clock = clock
        self._codes: dict[str, float] = {}  # code -> expiry time
        self._sessions: list[str] = []
        self._lock = threading.Lock()

    def mint_login_code(self) -> str:
        """Create a single-use login code that expires after ``code_ttl`` seconds.

        Returns
        -------
        str
            The new code.
        """
        code = secrets.token_urlsafe(24)
        now = self._clock()
        with self._lock:
            # Forget codes that can no longer be used so the table stays small.
            self._codes = {c: exp for c, exp in self._codes.items() if exp > now}
            self._codes[code] = now + self._code_ttl
        return code

    def exchange(self, code: str) -> str | None:
        """Consume a login code and return a new session token.

        Parameters
        ----------
        code : str
            Code from ``mint_login_code``.

        Returns
        -------
        str | None
            A fresh session token, or None when the code is unknown, used or
            expired.
        """
        now = self._clock()
        with self._lock:
            # Find the code by constant-time comparison; it is removed whether
            # or not it has expired, so a code can never be tried twice.
            match = next((c for c in self._codes if secrets.compare_digest(c, code)), None)
            if match is None:
                return None
            expiry = self._codes.pop(match)
            if expiry <= now:
                return None
            token = secrets.token_urlsafe(32)
            self._sessions.append(token)
            return token

    def is_valid_session(self, token: str | None) -> bool:
        """Return whether ``token`` was issued by ``exchange``.

        Parameters
        ----------
        token : str | None
            Cookie value; None (no cookie) is never valid.

        Returns
        -------
        bool
            True for a token that ``exchange`` returned earlier.
        """
        if not token:
            return False
        with self._lock:
            return any(secrets.compare_digest(token, known) for known in self._sessions)
