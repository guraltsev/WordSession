"""Run the local HTTP API in a background thread bound to localhost.

Call ``start_server(service)`` to serve the manager on a free port and keep
the returned ``ServerHandle`` to mint login codes and to stop the server.
"""

import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import uvicorn

from word_session.service import SessionService
from word_session.web.app import create_app
from word_session.web.auth import Auth


@dataclass
class ServerHandle:
    """Describe a running local server and allow stopping it.

    Attributes
    ----------
    port : int
        The TCP port actually bound on 127.0.0.1.
    url : str
        Base URL, ``http://127.0.0.1:<port>``.
    auth : Auth
        Authentication state; use it to mint login codes.
    """

    port: int
    url: str
    auth: Auth
    _server: uvicorn.Server = field(repr=False)
    _thread: threading.Thread = field(repr=False)
    _sock: socket.socket = field(repr=False)

    def stop(self, timeout: float = 5.0) -> None:
        """Ask the server to exit, wait for its thread and release the port.

        Parameters
        ----------
        timeout : float
            Seconds to wait for the server thread to finish.
        """
        self._server.should_exit = True
        self._thread.join(timeout)
        self._sock.close()


def start_server(
    service: SessionService,
    *,
    port: int = 0,
    on_shutdown: Callable[[], None] | None = None,
) -> ServerHandle:
    """Start the HTTP API on 127.0.0.1 in a daemon thread.

    Parameters
    ----------
    service : SessionService
        Service the API exposes.
    port : int
        Port to bind; 0 picks a free one.
    on_shutdown : Callable[[], None] | None
        Enables ``POST /api/internal/shutdown`` and is called by it.

    Returns
    -------
    ServerHandle
        Handle with the real port, base URL, auth state and ``stop()``.

    Raises
    ------
    RuntimeError
        If the server does not start within 10 seconds.
    """
    # Bind first so the real port is known before the app is built.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", port))
    real_port = sock.getsockname()[1]

    # Build the app and the uvicorn server around that socket.
    auth = Auth()
    app = create_app(service, auth, port=real_port, on_shutdown=on_shutdown)
    config = uvicorn.Config(app, log_config=None, access_log=False, timeout_graceful_shutdown=2)
    server = uvicorn.Server(config)
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [sock]}, name="http-server", daemon=True
    )
    thread.start()

    # Wait until uvicorn accepts connections, or give up and clean up.
    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            server.should_exit = True
            thread.join(2)
            sock.close()
            raise RuntimeError("HTTP server did not start")
        time.sleep(0.02)

    return ServerHandle(
        port=real_port,
        url=f"http://127.0.0.1:{real_port}",
        auth=auth,
        _server=server,
        _thread=thread,
        _sock=sock,
    )
