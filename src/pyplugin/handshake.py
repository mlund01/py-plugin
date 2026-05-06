"""go-plugin stdout handshake protocol.

Wire format (single line, ``\\n`` terminated, written by plugin to stdout)::

    CORE | APP | NETWORK | ADDRESS | PROTOCOL | SERVER-CERT [ | MULTIPLEX ]

* CORE: int. Always ``1`` (CoreProtocolVersion). Anything else is a hard reject.
* APP: int. Application-defined protocol version.
* NETWORK: ``unix`` or ``tcp``.
* ADDRESS: socket path or ``ip:port``.
* PROTOCOL: ``grpc`` (we don't implement Go's net/rpc).
* SERVER-CERT: empty when AutoMTLS is off, else base64.RawStdEncoding of the
  server's leaf cert in raw DER. Length > 50 distinguishes a real cert from
  legacy "extra" data — that's how the Go client sniffs it.
* MULTIPLEX: optional 7th field, ``true`` when GRPCBrokerMultiplex is supported.

Format mirrors `hashicorp/go-plugin server.go::Serve` exactly.
"""
from __future__ import annotations

from dataclasses import dataclass

from .errors import CoreProtocolMismatch, HandshakeError

CORE_PROTOCOL_VERSION = 1
PROTOCOL_GRPC = "grpc"
PROTOCOL_NETRPC = "netrpc"

NETWORK_UNIX = "unix"
NETWORK_TCP = "tcp"


@dataclass(frozen=True)
class HandshakeConfig:
    """Plugin/host handshake config. Mirrors go-plugin's HandshakeConfig.

    Both sides must agree on these for a plugin to load.
    """
    protocol_version: int
    magic_cookie_key: str
    magic_cookie_value: str


@dataclass(frozen=True)
class HandshakeLine:
    """Parsed handshake line."""
    core_protocol_version: int
    app_protocol_version: int
    network: str
    address: str
    protocol: str
    server_cert: str = ""
    multiplex_supported: bool = False


def format_line(
    *,
    app_protocol_version: int,
    network: str,
    address: str,
    protocol: str = PROTOCOL_GRPC,
    server_cert: str = "",
    multiplex_supported: bool | None = None,
) -> str:
    """Build the handshake line a plugin should write to stdout.

    Always emits 6 segments (matching go-plugin); appends a 7th only when
    multiplex_supported is not None (i.e. the env opted in).
    """
    line = f"{CORE_PROTOCOL_VERSION}|{app_protocol_version}|{network}|{address}|{protocol}|{server_cert}"
    if multiplex_supported is not None:
        line += f"|{'true' if multiplex_supported else 'false'}"
    return line


def parse_line(raw: str) -> HandshakeLine:
    """Parse a handshake line. Tolerant of 4..7 segments to match go-plugin."""
    line = raw.strip()
    parts = line.split("|")
    if len(parts) < 4:
        raise HandshakeError(f"unrecognized remote plugin message: {raw!r}")

    try:
        core = int(parts[0])
    except ValueError as e:
        raise HandshakeError(f"error parsing core protocol version: {e}") from e
    if core != CORE_PROTOCOL_VERSION:
        raise CoreProtocolMismatch(
            f"incompatible core API version with plugin. "
            f"Plugin version: {parts[0]}, Core version: {CORE_PROTOCOL_VERSION}"
        )

    try:
        app = int(parts[1])
    except ValueError as e:
        raise HandshakeError(f"error parsing app protocol version: {e}") from e

    network = parts[2]
    address = parts[3]
    # Default to netrpc for backward compat with very old Go plugins, mirroring client.go.
    protocol = parts[4] if len(parts) >= 5 else PROTOCOL_NETRPC

    # The Go client uses len(parts[5]) > 50 to decide if a real cert is present
    # (older plugins emit some unrelated "extra" data here).
    server_cert = ""
    if len(parts) >= 6 and len(parts[5]) > 50:
        server_cert = parts[5]

    multiplex = False
    if len(parts) >= 7:
        multiplex = parts[6].lower() == "true"

    return HandshakeLine(
        core_protocol_version=core,
        app_protocol_version=app,
        network=network,
        address=address,
        protocol=protocol,
        server_cert=server_cert,
        multiplex_supported=multiplex,
    )
