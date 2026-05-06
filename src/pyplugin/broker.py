"""GRPCBroker — bidi sub-channel multiplexer (grpclib async).

Same semantics as go-plugin's non-multiplexed broker: ``accept_and_serve(id, …)``
opens a fresh listener and sends a ``ConnInfo`` over the broker stream;
``dial(id)`` waits for that ``ConnInfo`` and opens a channel to the address.
A demux task pumps inbound stream messages into per-id ``asyncio.Queue``s.

Multiplexing the broker over the main socket (``PLUGIN_MULTIPLEX_GRPC``) is
not implemented — we always advertise ``false`` if the env var is set.

Sub-channels use mTLS reusing the same cert material as the main channel:
each side has its leaf cert and key, plus the peer's cert pinned as trust root.
We hold those PEMs on the broker so we can build the correct SSL context
(server-side for ``accept_and_serve``, client-side for ``dial``).
"""
from __future__ import annotations

import asyncio
import itertools
import ssl
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from grpclib.client import Channel
from grpclib.config import Configuration
from grpclib.server import Server, Stream

from . import mtls
from ._generated import grpc_broker_grpc, grpc_broker_pb2
from .transport import open_listener


_DIAL_TIMEOUT = 5.0


@dataclass(frozen=True)
class TLSMaterial:
    """PEM bytes used to derive per-direction SSL contexts."""
    cert_pem: bytes
    key_pem: bytes
    peer_cert_pem: bytes


class _ServerStreamServicer(grpc_broker_grpc.GRPCBrokerBase):
    """Plugin-side bridge: pumps a single bidi stream into per-side queues."""

    def __init__(self) -> None:
        self.incoming: asyncio.Queue[grpc_broker_pb2.ConnInfo | None] = asyncio.Queue()
        self.outgoing: asyncio.Queue[grpc_broker_pb2.ConnInfo | None] = asyncio.Queue()
        self.connected = asyncio.Event()

    async def StartStream(self, stream: Stream) -> None:  # noqa: N802
        self.connected.set()

        async def reader() -> None:
            try:
                async for msg in stream:
                    await self.incoming.put(msg)
            finally:
                await self.incoming.put(None)

        async def writer() -> None:
            while True:
                msg = await self.outgoing.get()
                if msg is None:
                    return
                await stream.send_message(msg)

        await asyncio.gather(reader(), writer(), return_exceptions=True)


class GRPCBroker:
    """Public broker facade. Lives on both host and plugin sides."""

    def __init__(
        self,
        *,
        send: Callable[[grpc_broker_pb2.ConnInfo], Awaitable[None]],
        close: Callable[[], None],
        tls: Optional[TLSMaterial] = None,
    ) -> None:
        self._send = send
        self._close = close
        self._tls = tls
        self._lock = asyncio.Lock()
        self._pending: dict[int, asyncio.Queue[grpc_broker_pb2.ConnInfo]] = {}
        self._next_id = itertools.count(1)
        self._closed = False
        self._servers: list[Server] = []

    def next_id(self) -> int:
        return next(self._next_id)

    def _q_for(self, sid: int) -> asyncio.Queue[grpc_broker_pb2.ConnInfo]:
        q = self._pending.get(sid)
        if q is None:
            q = asyncio.Queue(maxsize=1)
            self._pending[sid] = q
        return q

    async def deliver(self, msg: grpc_broker_pb2.ConnInfo) -> None:
        """Run-loop callback — push an incoming message onto the per-id queue."""
        q = self._q_for(msg.service_id)
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass  # drop duplicate Knock/ack — not used for non-mux model

    def _server_ssl(self) -> Optional[ssl.SSLContext]:
        if self._tls is None:
            return None
        return mtls.server_ssl_context(
            cert_pem=self._tls.cert_pem,
            key_pem=self._tls.key_pem,
            peer_cert_pem=self._tls.peer_cert_pem,
        )

    def _client_ssl(self) -> Optional[ssl.SSLContext]:
        if self._tls is None:
            return None
        return mtls.client_ssl_context(
            cert_pem=self._tls.cert_pem,
            key_pem=self._tls.key_pem,
            peer_cert_pem=self._tls.peer_cert_pem,
        )

    async def accept_and_serve(self, service_id: int, servicers: list) -> Server:
        """Open a fresh listener, run a grpclib ``Server`` on it for ``service_id``,
        and notify the peer via the broker stream."""
        listener = open_listener()
        server = Server(servicers)
        srv_ssl = self._server_ssl()
        if listener.network == "unix":
            await server.start(path=listener.address, ssl=srv_ssl)
        else:
            host, port = listener.address.split(":")
            await server.start(host=host, port=int(port), ssl=srv_ssl)
        self._servers.append(server)
        await self._send(grpc_broker_pb2.ConnInfo(
            service_id=service_id, network=listener.network, address=listener.address,
        ))
        return server

    async def dial(self, service_id: int, *, timeout: float = _DIAL_TIMEOUT) -> Channel:
        """Wait for the peer's ``ConnInfo`` for ``service_id`` and open a channel."""
        q = self._q_for(service_id)
        try:
            ci = await asyncio.wait_for(q.get(), timeout=timeout)
        except asyncio.TimeoutError as e:
            raise TimeoutError(f"timeout waiting for broker conn info for id {service_id}") from e

        cli_ssl = self._client_ssl()
        cfg = Configuration(ssl_target_name_override="localhost") if cli_ssl else None
        if ci.network == "unix":
            return Channel(path=ci.address, ssl=cli_ssl, config=cfg)
        host, port = ci.address.split(":")
        return Channel(host=host, port=int(port), ssl=cli_ssl, config=cfg)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for srv in self._servers:
            srv.close()
            try:
                await srv.wait_closed()
            except Exception:  # noqa: BLE001
                pass
        self._close()


def make_server_side_broker(tls: TLSMaterial | None) -> tuple[_ServerStreamServicer, GRPCBroker, "asyncio.Task[None]"]:
    """Build (servicer, broker, demux-task) for the plugin side."""
    servicer = _ServerStreamServicer()

    async def send(msg: grpc_broker_pb2.ConnInfo) -> None:
        await servicer.outgoing.put(msg)

    def close() -> None:
        servicer.outgoing.put_nowait(None)

    broker = GRPCBroker(send=send, close=close, tls=tls)

    async def demux() -> None:
        while True:
            msg = await servicer.incoming.get()
            if msg is None:
                return
            await broker.deliver(msg)

    return servicer, broker, asyncio.ensure_future(demux())


def make_client_side_broker(channel: Channel, tls: TLSMaterial | None) -> tuple[GRPCBroker, "asyncio.Task[None]"]:
    """Build (broker, run-task) for the host side, dialing StartStream."""
    stub = grpc_broker_grpc.GRPCBrokerStub(channel)
    outgoing: asyncio.Queue[grpc_broker_pb2.ConnInfo | None] = asyncio.Queue()
    stream_holder: dict = {}

    async def send(msg: grpc_broker_pb2.ConnInfo) -> None:
        await outgoing.put(msg)

    def close() -> None:
        outgoing.put_nowait(None)

    broker = GRPCBroker(send=send, close=close, tls=tls)

    async def runner() -> None:
        async with stub.StartStream.open() as stream:
            stream_holder["stream"] = stream

            async def writer() -> None:
                while True:
                    msg = await outgoing.get()
                    if msg is None:
                        return
                    await stream.send_message(msg)

            async def reader() -> None:
                async for msg in stream:
                    await broker.deliver(msg)

            await asyncio.gather(writer(), reader(), return_exceptions=True)

    return broker, asyncio.ensure_future(runner())
