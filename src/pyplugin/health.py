"""Minimal grpc.health.v1 servicer that returns SERVING for go-plugin's "plugin" name.

go-plugin's host pings ``Check(service="plugin")`` and expects ``SERVING``.
grpclib ships a more elaborate Health service that derives names from registered
``IServable`` objects' method mappings — we just need a single static name
matching go-plugin's wire convention.
"""
from __future__ import annotations

from grpclib.const import Status
from grpclib.health.v1 import health_grpc, health_pb2


class StaticHealth(health_grpc.HealthBase):
    """Returns SERVING for any registered service name; NOT_FOUND otherwise."""

    def __init__(self, services: list[str] | None = None) -> None:
        # "" is the "overall" service name; "plugin" is what go-plugin pings.
        self._services = set(services or ["", "plugin"])

    async def Check(self, stream) -> None:  # noqa: N802
        request = await stream.recv_message()
        if request.service in self._services:
            await stream.send_message(health_pb2.HealthCheckResponse(
                status=health_pb2.HealthCheckResponse.SERVING,
            ))
        else:
            await stream.send_trailing_metadata(status=Status.NOT_FOUND)

    async def Watch(self, stream) -> None:  # noqa: N802
        # Not used by go-plugin; emit a single response and close.
        request = await stream.recv_message()
        if request.service in self._services:
            await stream.send_message(health_pb2.HealthCheckResponse(
                status=health_pb2.HealthCheckResponse.SERVING,
            ))
        else:
            await stream.send_trailing_metadata(status=Status.NOT_FOUND)
