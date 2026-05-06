"""GRPCStdio servicer — streams plugin stdout/stderr writes to the host (grpclib async)."""
from __future__ import annotations

import asyncio

from ._generated import grpc_stdio_grpc, grpc_stdio_pb2


class GRPCStdioServicer(grpc_stdio_grpc.GRPCStdioBase):
    """Streams stdio chunks. ``StreamStdio`` is called once by the host."""

    def __init__(self) -> None:
        self._q: asyncio.Queue[grpc_stdio_pb2.StdioData | None] = asyncio.Queue()
        self._consumed = asyncio.Event()

    def write_stdout(self, data: bytes) -> None:
        if data:
            self._q.put_nowait(grpc_stdio_pb2.StdioData(
                channel=grpc_stdio_pb2.StdioData.STDOUT, data=data))

    def write_stderr(self, data: bytes) -> None:
        if data:
            self._q.put_nowait(grpc_stdio_pb2.StdioData(
                channel=grpc_stdio_pb2.StdioData.STDERR, data=data))

    def close(self) -> None:
        self._q.put_nowait(None)

    async def StreamStdio(self, stream) -> None:  # noqa: N802
        await stream.recv_message()  # request is google.protobuf.Empty
        self._consumed.set()
        while True:
            chunk = await self._q.get()
            if chunk is None:
                return
            await stream.send_message(chunk)
