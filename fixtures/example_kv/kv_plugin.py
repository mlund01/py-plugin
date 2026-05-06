"""Shared Plugin definition + handshake config for the example KV service."""
from __future__ import annotations

from typing import Any

import grpc

from pyplugin import HandshakeConfig, Plugin
from pyplugin.broker import GRPCBroker

from .generated import callback_pb2, callback_pb2_grpc, kv_pb2, kv_pb2_grpc

HANDSHAKE = HandshakeConfig(
    protocol_version=1,
    magic_cookie_key="BASIC_PLUGIN",
    magic_cookie_value="hello",
)


class KVServicer(kv_pb2_grpc.KVServicer):
    def __init__(self, broker=None) -> None:
        self.store: dict[str, bytes] = {}
        self.broker = broker

    def Get(self, request, context):
        return kv_pb2.GetResponse(value=self.store.get(request.key, b""))

    def Put(self, request, context):
        self.store[request.key] = request.value
        return kv_pb2.Empty()

    def PingHost(self, request, context):
        # Dial back into the host's Callback service via the broker.
        assert self.broker is not None, "broker not configured"
        ch = self.broker.dial(request.broker_id)
        try:
            stub = callback_pb2_grpc.CallbackStub(ch)
            resp = stub.Notify(callback_pb2.NotifyRequest(note=request.note), timeout=5.0)
            return kv_pb2.PingHostResponse(echo=resp.echo)
        finally:
            ch.close()


class KVPlugin(Plugin):
    """Plugin glue that registers the KV service and builds a stub on dial."""

    def __init__(self, servicer: KVServicer | None = None) -> None:
        self._servicer = servicer

    def grpc_server(self, broker: GRPCBroker, server: grpc.Server) -> None:
        if self._servicer is None:
            self._servicer = KVServicer(broker=broker)
        else:
            self._servicer.broker = broker
        kv_pb2_grpc.add_KVServicer_to_server(self._servicer, server)

    def grpc_client(self, broker: GRPCBroker, channel: grpc.Channel) -> Any:
        return kv_pb2_grpc.KVStub(channel)
