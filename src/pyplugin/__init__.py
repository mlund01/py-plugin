"""pyplugin — wire-compatible Python port of HashiCorp's go-plugin."""
from __future__ import annotations

from .broker import GRPCBroker
from .client import Client, ClientConfig
from .errors import (
    AppProtocolMismatch,
    CoreProtocolMismatch,
    HandshakeError,
    MagicCookieMismatch,
    ProcessExitedError,
    PyPluginError,
    StartTimeout,
    TLSError,
    UnsupportedProtocol,
)
from .handshake import (
    CORE_PROTOCOL_VERSION,
    HandshakeConfig,
    HandshakeLine,
    NETWORK_TCP,
    NETWORK_UNIX,
    PROTOCOL_GRPC,
)
from .plugin import Plugin, PluginSet, VersionedPlugins
from .reattach import ReattachConfig
from .server import ServeConfig, serve

__all__ = [
    "CORE_PROTOCOL_VERSION",
    "Client",
    "ClientConfig",
    "GRPCBroker",
    "HandshakeConfig",
    "HandshakeLine",
    "NETWORK_TCP",
    "NETWORK_UNIX",
    "PROTOCOL_GRPC",
    "Plugin",
    "PluginSet",
    "ReattachConfig",
    "ServeConfig",
    "VersionedPlugins",
    "serve",
    "PyPluginError",
    "HandshakeError",
    "CoreProtocolMismatch",
    "AppProtocolMismatch",
    "UnsupportedProtocol",
    "MagicCookieMismatch",
    "ProcessExitedError",
    "StartTimeout",
    "TLSError",
]
