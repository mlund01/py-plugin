"""GRPCStdio servicer — streams plugin stdout/stderr writes to the host.

Used after the handshake line has been emitted. Plugin code that prints to
stdout/stderr post-handshake gets captured and streamed to the host as
``StdioData{channel, data}`` messages. Optional but registered by default
to match go-plugin.
"""
from __future__ import annotations

import queue
import threading
from typing import Iterator

from ._generated import grpc_stdio_pb2, grpc_stdio_pb2_grpc


class GRPCStdioServicer(grpc_stdio_pb2_grpc.GRPCStdioServicer):
    """Streams stdio chunks. ``StreamStdio`` may only be called once.

    Plugin code feeds chunks via :meth:`write_stdout` / :meth:`write_stderr`;
    the gRPC stream drains them in order.
    """

    def __init__(self) -> None:
        self._q: queue.Queue[grpc_stdio_pb2.StdioData | None] = queue.Queue()
        self._consumed = threading.Event()

    def write_stdout(self, data: bytes) -> None:
        if not self._consumed.is_set() or not data:
            self._q.put(grpc_stdio_pb2.StdioData(
                channel=grpc_stdio_pb2.StdioData.STDOUT, data=data))

    def write_stderr(self, data: bytes) -> None:
        if not self._consumed.is_set() or not data:
            self._q.put(grpc_stdio_pb2.StdioData(
                channel=grpc_stdio_pb2.StdioData.STDERR, data=data))

    def close(self) -> None:
        self._q.put(None)

    def StreamStdio(self, request, context) -> Iterator[grpc_stdio_pb2.StdioData]:  # noqa: N802
        self._consumed.set()
        while True:
            chunk = self._q.get()
            if chunk is None:
                return
            yield chunk
