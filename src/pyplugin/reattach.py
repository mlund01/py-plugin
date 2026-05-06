"""ReattachConfig — host re-connects to a pre-existing plugin process."""
from __future__ import annotations

from dataclasses import dataclass

from .handshake import NETWORK_UNIX, PROTOCOL_GRPC


@dataclass(frozen=True)
class ReattachConfig:
    """Information needed to re-attach to a running plugin without spawning.

    Mirrors go-plugin's ``ReattachConfig``. ``test=True`` (set by serving with
    ``ServeConfig.test_mode``) tells the host's ``kill()`` to NOT terminate
    the process — the test harness is responsible for shutdown.
    """
    pid: int
    addr: str                      # unix path or "host:port"
    network: str = NETWORK_UNIX
    protocol: str = PROTOCOL_GRPC
    protocol_version: int = 1
    server_cert_pem: bytes | None = None  # for AutoMTLS reattach
    # If reattaching with AutoMTLS, the host must supply the *original* host
    # client cert+key it generated for the plugin so the TLS handshake works.
    client_cert_pem: bytes | None = None
    client_key_pem: bytes | None = None
    test: bool = False
