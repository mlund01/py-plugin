"""Public exception hierarchy for pyplugin."""
from __future__ import annotations


class PyPluginError(Exception):
    """Base for all pyplugin errors."""


class HandshakeError(PyPluginError):
    """Plugin's stdout handshake line was malformed or missing."""


class CoreProtocolMismatch(HandshakeError):
    """Plugin advertised a core protocol version we don't speak."""


class AppProtocolMismatch(HandshakeError):
    """Plugin advertised an app protocol version not in our VersionedPlugins."""


class UnsupportedProtocol(HandshakeError):
    """Plugin advertised a wire protocol other than 'grpc' (e.g. 'netrpc')."""


class MagicCookieMismatch(PyPluginError):
    """Plugin's magic cookie env var didn't match. Plugin author bug or a user
    invoking the plugin binary directly."""


class ProcessExitedError(PyPluginError):
    """The plugin subprocess exited before we could connect or during a call."""


class TLSError(PyPluginError):
    """AutoMTLS setup or verification failed."""


class StartTimeout(PyPluginError):
    """Plugin did not emit a handshake within the configured start_timeout."""
