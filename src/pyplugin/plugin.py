"""Plugin ABC and type aliases (grpclib version).

A pyplugin author implements one ``Plugin`` subclass per service exposed.
``servicers`` returns the grpclib ``Base`` instances to register on the
plugin-side server; ``stub`` builds a typed client stub on the host side
from an open ``grpclib.client.Channel``.

Mirrors go-plugin's ``GRPCPlugin`` interface — both methods receive the
``GRPCBroker`` so plugins can request callbacks back into the host.
"""
from __future__ import annotations

import abc
from typing import Any, Mapping, TYPE_CHECKING

from grpclib.client import Channel

if TYPE_CHECKING:
    from .broker import GRPCBroker


class Plugin(abc.ABC):
    """Abstract base for a plugin type."""

    @abc.abstractmethod
    def servicers(self, broker: "GRPCBroker") -> list:
        """Return grpclib servicer instances to register on the plugin server.

        Called once on the plugin side during ``serve()`` setup.
        """

    @abc.abstractmethod
    def stub(self, broker: "GRPCBroker", channel: Channel) -> Any:
        """Build a typed grpclib client stub from an open channel (host side)."""


PluginSet = Mapping[str, Plugin]
VersionedPlugins = Mapping[int, PluginSet]
