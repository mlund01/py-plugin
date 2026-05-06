"""Plugin ABC and type aliases.

A pyplugin user implements one ``Plugin`` subclass per service exposed.
``grpc_server`` registers the gRPC service on the plugin-side server;
``grpc_client`` builds a stub on the host side from an open channel.

Mirrors go-plugin's ``GRPCPlugin`` interface — both methods take the
``GRPCBroker`` so plugins can request callbacks back into the host.
"""
from __future__ import annotations

import abc
from typing import Any, Mapping, TYPE_CHECKING

import grpc

if TYPE_CHECKING:
    from .broker import GRPCBroker


class Plugin(abc.ABC):
    """Abstract base for a plugin type."""

    @abc.abstractmethod
    def grpc_server(self, broker: "GRPCBroker", server: grpc.Server) -> None:
        """Register this plugin's gRPC service on ``server`` (plugin-side)."""

    @abc.abstractmethod
    def grpc_client(self, broker: "GRPCBroker", channel: grpc.Channel) -> Any:
        """Build a typed client stub from an open gRPC channel (host-side)."""


PluginSet = Mapping[str, Plugin]
VersionedPlugins = Mapping[int, PluginSet]
