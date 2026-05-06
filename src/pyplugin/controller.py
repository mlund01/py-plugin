"""GRPCController.Shutdown servicer (grpclib async)."""
from __future__ import annotations

import asyncio

from ._generated import grpc_controller_grpc, grpc_controller_pb2


class GRPCControllerServicer(grpc_controller_grpc.GRPCControllerBase):
    """Sets a shutdown ``asyncio.Event`` when ``Shutdown`` is invoked.

    Mirrors go-plugin's grpcControllerServer: ``Shutdown`` returns immediately
    with Empty; the serve loop awaits the event, then closes the gRPC server.
    """

    def __init__(self) -> None:
        self.shutdown_event = asyncio.Event()

    async def Shutdown(self, stream) -> None:  # noqa: N802
        await stream.recv_message()
        await stream.send_message(grpc_controller_pb2.Empty())
        self.shutdown_event.set()
