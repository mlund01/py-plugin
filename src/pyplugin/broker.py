"""GRPCBroker — bidirectional sub-channel multiplexer.

go-plugin uses a single bidi gRPC stream (``GRPCBroker.StartStream``) to
negotiate addresses for additional gRPC channels in either direction. The
host or plugin asks the other side to open a listener with a service id;
the other side replies with a ``ConnInfo`` carrying the new listener's
address; the requester then dials it.

This implementation does NOT do socket multiplexing (that's the
``PLUGIN_MULTIPLEX_GRPC`` mode). Each sub-channel is a fresh listener,
matching the ``b.muxer == nil`` path in go-plugin's ``grpc_broker.go``.
"""
from __future__ import annotations

import itertools
import queue
import threading
from typing import Callable, Optional

import grpc

from ._generated import grpc_broker_pb2, grpc_broker_pb2_grpc
from .transport import grpc_dial_target, open_listener


_DIAL_TIMEOUT = 5.0


class _PendingStream:
    __slots__ = ("ch", "done")

    def __init__(self) -> None:
        self.ch: queue.Queue[grpc_broker_pb2.ConnInfo] = queue.Queue(maxsize=1)
        self.done = threading.Event()


class _BrokerStreamServicer(grpc_broker_pb2_grpc.GRPCBrokerServicer):
    """Server side of the bidi stream.

    Bridges the gRPC stream to two queues:
    * ``incoming`` — every ``ConnInfo`` received from the peer.
    * ``outgoing`` — ``ConnInfo``s the broker wants to send to the peer.
    A single sender thread pulls from ``outgoing`` and ``yield``s.
    """

    def __init__(self) -> None:
        self.incoming: queue.Queue[grpc_broker_pb2.ConnInfo] = queue.Queue()
        self.outgoing: queue.Queue[Optional[grpc_broker_pb2.ConnInfo]] = queue.Queue()
        self._connected = threading.Event()

    def StartStream(self, request_iterator, context):  # noqa: N802
        self._connected.set()

        def reader():
            try:
                for msg in request_iterator:
                    self.incoming.put(msg)
            finally:
                self.incoming.put(None)  # type: ignore[arg-type]

        t = threading.Thread(target=reader, name="broker-reader", daemon=True)
        t.start()

        while True:
            msg = self.outgoing.get()
            if msg is None:
                return
            yield msg

    def wait_connected(self, timeout: float | None = None) -> bool:
        return self._connected.wait(timeout=timeout)

    def send(self, msg: grpc_broker_pb2.ConnInfo) -> None:
        self.outgoing.put(msg)

    def close(self) -> None:
        self.outgoing.put(None)


class GRPCBroker:
    """Public broker facade. Lives on both host and plugin sides.

    On the plugin side, the broker is constructed around a server-side
    bidi stream (the broker IS the gRPC server endpoint). On the host
    side, it dials ``GRPCBrokerStub.StartStream`` and pumps the same.

    Either side may call :meth:`accept_and_serve` (open a new listener and
    serve a registered gRPC server on it) or :meth:`dial` (open a channel
    to a sub-stream the peer has opened).
    """

    def __init__(self, *, send: Callable[[grpc_broker_pb2.ConnInfo], None], close: Callable[[], None]) -> None:
        self._send = send
        self._close = close
        self._lock = threading.Lock()
        self._pending: dict[int, _PendingStream] = {}
        self._next_id = itertools.count(1)
        self._closed = False
        self._tls_root: bytes | None = None
        self._tls_client_cert: bytes | None = None
        self._tls_client_key: bytes | None = None

    def configure_tls(self, *, root_cert_pem: bytes, client_cert_pem: bytes | None = None,
                      client_key_pem: bytes | None = None) -> None:
        self._tls_root = root_cert_pem
        self._tls_client_cert = client_cert_pem
        self._tls_client_key = client_key_pem

    def next_id(self) -> int:
        return next(self._next_id)

    def _pending_for(self, sid: int) -> _PendingStream:
        with self._lock:
            p = self._pending.get(sid)
            if p is None:
                p = _PendingStream()
                self._pending[sid] = p
            return p

    def deliver(self, msg: grpc_broker_pb2.ConnInfo) -> None:
        """Called by the run loop for every incoming message from the peer."""
        p = self._pending_for(msg.service_id)
        try:
            p.ch.put_nowait(msg)
        except queue.Full:
            pass

    def accept_and_serve(self, service_id: int, register: Callable[[grpc.Server], None]) -> grpc.Server:
        """Open a new listener and start a gRPC server on it for ``service_id``.

        Returns the running ``grpc.Server`` (caller can stop it). Sends the
        listener's address to the peer on the broker stream so the peer's
        :meth:`dial` can reach it.
        """
        from concurrent import futures
        listener = open_listener()
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
        register(server)
        if self._tls_root is not None:
            from grpc import ssl_server_credentials
            creds = ssl_server_credentials(
                [(self._tls_client_key or b"", self._tls_client_cert or b"")],
                root_certificates=self._tls_root,
                require_client_auth=True,
            )
            server.add_secure_port(listener.grpc_target, creds)
        else:
            server.add_insecure_port(listener.grpc_target)
        server.start()

        self._send(grpc_broker_pb2.ConnInfo(
            service_id=service_id, network=listener.network, address=listener.address,
        ))
        return server

    def dial(self, service_id: int, *, timeout: float = _DIAL_TIMEOUT) -> grpc.Channel:
        """Wait for the peer's accept and dial a channel to it."""
        p = self._pending_for(service_id)
        try:
            ci = p.ch.get(timeout=timeout)
        except queue.Empty as e:
            raise TimeoutError(f"timeout waiting for broker conn info for id {service_id}") from e
        target = grpc_dial_target(ci.network, ci.address)
        if self._tls_root is not None:
            from grpc import ssl_channel_credentials, secure_channel
            creds = ssl_channel_credentials(
                root_certificates=self._tls_root,
                private_key=self._tls_client_key,
                certificate_chain=self._tls_client_cert,
            )
            return secure_channel(target, creds, options=(("grpc.ssl_target_name_override", "localhost"),))
        return grpc.insecure_channel(target)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._close()


# ---------------------------------------------------------------------------
# Run-loops bridging stream <-> broker for each side.
# ---------------------------------------------------------------------------

def make_server_side_broker() -> tuple[_BrokerStreamServicer, GRPCBroker, threading.Thread]:
    """Build the (servicer, broker, demux-thread) trio for the plugin side."""
    servicer = _BrokerStreamServicer()
    broker = GRPCBroker(send=servicer.send, close=servicer.close)

    def demux():
        while True:
            msg = servicer.incoming.get()
            if msg is None:
                return
            broker.deliver(msg)

    t = threading.Thread(target=demux, name="broker-demux-server", daemon=True)
    return servicer, broker, t


def make_client_side_broker(channel: grpc.Channel) -> tuple[GRPCBroker, threading.Thread]:
    """Build (broker, run-thread) for the host side, dialing StartStream."""
    stub = grpc_broker_pb2_grpc.GRPCBrokerStub(channel)
    outgoing: queue.Queue[Optional[grpc_broker_pb2.ConnInfo]] = queue.Queue()
    incoming: queue.Queue[Optional[grpc_broker_pb2.ConnInfo]] = queue.Queue()

    def send(msg: grpc_broker_pb2.ConnInfo) -> None:
        outgoing.put(msg)

    def close() -> None:
        outgoing.put(None)

    broker = GRPCBroker(send=send, close=close)

    def request_iter():
        while True:
            m = outgoing.get()
            if m is None:
                return
            yield m

    def runner():
        try:
            for msg in stub.StartStream(request_iter()):
                broker.deliver(msg)
        except grpc.RpcError:
            return

    t = threading.Thread(target=runner, name="broker-client", daemon=True)
    return broker, t
