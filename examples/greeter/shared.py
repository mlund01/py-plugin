"""Shared between host and plugin: handshake config + the Plugin glue class.

In a real project, host and plugin would be separate Python packages that both
depend on this shared module — exactly like go-plugin's ``shared/interface.go``.
"""
from __future__ import annotations

from typing import Any

from grpclib.client import Channel

from pyplugin import HandshakeConfig, Plugin
from pyplugin.broker import GRPCBroker

from .generated import greeter_grpc, greeter_pb2

HANDSHAKE = HandshakeConfig(
    protocol_version=1,
    magic_cookie_key="GREETER_PLUGIN",
    magic_cookie_value="hello-from-pyplugin",
)


class GreeterServicer(greeter_grpc.GreeterBase):
    """Plugin-side implementation. Lives in the plugin process."""

    async def Greet(self, stream) -> None:
        request = await stream.recv_message()
        await stream.send_message(
            greeter_pb2.GreetResponse(message=f"hello, {request.name}!")
        )

    async def Count(self, stream) -> None:
        request = await stream.recv_message()
        await stream.send_message(greeter_pb2.CountResponse(
            letters=sum(1 for ch in request.text if ch.isalpha()),
            words=len(request.text.split()),
        ))


class GreeterPlugin(Plugin):
    """Glue used by both sides:

    * On the plugin side, ``servicers()`` returns the servicer instances to register.
    * On the host side, ``stub()`` builds the typed grpclib client.
    """

    def servicers(self, broker: GRPCBroker) -> list:
        return [GreeterServicer()]

    def stub(self, broker: GRPCBroker, channel: Channel) -> Any:
        return greeter_grpc.GreeterStub(channel)
