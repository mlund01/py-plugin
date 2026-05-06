"""GRPCController.Shutdown servicer — graceful shutdown for the plugin server."""
from __future__ import annotations

import threading

from ._generated import grpc_controller_pb2, grpc_controller_pb2_grpc


class GRPCControllerServicer(grpc_controller_pb2_grpc.GRPCControllerServicer):
    """Tracks a shutdown event the serve loop blocks on.

    Mirrors go-plugin's grpcControllerServer: ``Shutdown`` returns immediately,
    after which the serve loop calls ``server.stop(grace=...)`` and exits.
    """

    def __init__(self) -> None:
        self.shutdown_event = threading.Event()

    def Shutdown(self, request, context):  # noqa: N802 — proto method name
        self.shutdown_event.set()
        return grpc_controller_pb2.Empty()
