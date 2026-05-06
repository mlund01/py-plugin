"""Shared Plugin definition + handshake config for the example KV service (grpclib async)."""
from __future__ import annotations

from typing import Any

from grpclib.client import Channel

from pyplugin import HandshakeConfig, Plugin
from pyplugin.broker import GRPCBroker

from .generated import callback_grpc, callback_pb2, kv_grpc, kv_pb2

HANDSHAKE = HandshakeConfig(
    protocol_version=1,
    magic_cookie_key="BASIC_PLUGIN",
    magic_cookie_value="hello",
)


class KVServicer(kv_grpc.KVBase):
    def __init__(self, broker: GRPCBroker | None = None) -> None:
        self.store: dict[str, bytes] = {}
        self.broker = broker

    async def Get(self, stream) -> None:
        request = await stream.recv_message()
        await stream.send_message(kv_pb2.GetResponse(value=self.store.get(request.key, b"")))

    async def Put(self, stream) -> None:
        request = await stream.recv_message()
        self.store[request.key] = request.value
        await stream.send_message(kv_pb2.Empty())

    async def PingHost(self, stream) -> None:
        request = await stream.recv_message()
        assert self.broker is not None
        ch = await self.broker.dial(request.broker_id)
        try:
            stub = callback_grpc.CallbackStub(ch)
            resp = await stub.Notify(callback_pb2.NotifyRequest(note=request.note))
            await stream.send_message(kv_pb2.PingHostResponse(echo=resp.echo))
        finally:
            ch.close()


class KVPlugin(Plugin):
    """Plugin glue. ``servicers`` is called once during ``serve()``;
    ``stub`` is called by the host on dispense."""

    def __init__(self) -> None:
        self._servicer: KVServicer | None = None

    def servicers(self, broker: GRPCBroker) -> list:
        self._servicer = KVServicer(broker=broker)
        return [self._servicer]

    def stub(self, broker: GRPCBroker, channel: Channel) -> Any:
        return kv_grpc.KVStub(channel)
