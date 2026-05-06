"""Listener helpers — unix socket on POSIX, TCP loopback elsewhere or when forced.

Mirrors go-plugin's ``serverListener_unix`` / ``serverListener_tcp``.
"""
from __future__ import annotations

import os
import socket
import sys
import tempfile
from dataclasses import dataclass

from .handshake import NETWORK_TCP, NETWORK_UNIX

ENV_MIN_PORT = "PLUGIN_MIN_PORT"
ENV_MAX_PORT = "PLUGIN_MAX_PORT"
ENV_UNIX_SOCKET_DIR = "PLUGIN_UNIX_SOCKET_DIR"
ENV_UNIX_SOCKET_GROUP = "PLUGIN_UNIX_SOCKET_GROUP"


@dataclass
class Listener:
    """A bound listener ready for ``grpc.Server.add_*_port``."""
    network: str          # "unix" or "tcp"
    address: str          # "/tmp/plugin123" or "127.0.0.1:port"
    grpc_target: str      # what to pass to grpc: "unix:/tmp/sock" or "127.0.0.1:port"
    cleanup_path: str | None = None  # filesystem path to remove on close, if any


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def open_listener(*, force_tcp: bool = False) -> Listener:
    """Open a plugin-side listener following go-plugin's defaults.

    On Windows or when ``force_tcp``, picks an unused TCP port in the range
    given by ``PLUGIN_MIN_PORT``/``PLUGIN_MAX_PORT``. Otherwise creates a
    unique-named unix socket file (under ``PLUGIN_UNIX_SOCKET_DIR`` if set).
    """
    if force_tcp or _is_windows():
        return _open_tcp()
    return _open_unix()


def _open_unix() -> Listener:
    socket_dir = os.environ.get(ENV_UNIX_SOCKET_DIR) or None
    # Mirror go-plugin's serverListener_unix: claim a unique tempfile name,
    # remove the file, hand the (now non-existent) path to grpc which will
    # bind the unix socket itself.
    fd, path = tempfile.mkstemp(prefix="plugin", dir=socket_dir)
    os.close(fd)
    os.remove(path)
    return Listener(
        network=NETWORK_UNIX,
        address=path,
        grpc_target=f"unix:{path}",
        cleanup_path=path,
    )


def _open_tcp() -> Listener:
    min_port = int(os.environ.get(ENV_MIN_PORT) or 0)
    max_port = int(os.environ.get(ENV_MAX_PORT) or 0)

    if min_port == 0 and max_port == 0:
        # Pick a free port via OS.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return Listener(
            network=NETWORK_TCP,
            address=f"127.0.0.1:{port}",
            grpc_target=f"127.0.0.1:{port}",
        )

    if min_port > max_port:
        raise OSError(f"PLUGIN_MIN_PORT={min_port} > PLUGIN_MAX_PORT={max_port}")

    for port in range(min_port, max_port + 1):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            s.close()
            return Listener(
                network=NETWORK_TCP,
                address=f"127.0.0.1:{port}",
                grpc_target=f"127.0.0.1:{port}",
            )
        except OSError:
            s.close()
            continue
    raise OSError("couldn't bind plugin TCP listener in configured port range")


def grpc_dial_target(network: str, address: str) -> str:
    """Translate a (network, address) pair from a handshake into a grpc.Dial target."""
    if network == NETWORK_UNIX:
        return f"unix:{address}"
    if network == NETWORK_TCP:
        return address
    raise ValueError(f"unknown network type: {network!r}")
