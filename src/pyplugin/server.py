"""Plugin-side ``serve()`` entry point (grpclib async).

Mirrors go-plugin's ``Serve(opts *ServeConfig)`` lifecycle:

1. Validate magic cookie (or skip in test mode).
2. Negotiate protocol version against ``PLUGIN_PROTOCOL_VERSIONS``.
3. Open a listener (unix on POSIX, TCP loopback on Windows or when forced).
4. Build SSL context if ``PLUGIN_CLIENT_CERT`` is set (AutoMTLS).
5. Collect servicers: GRPCBroker + GRPCController + GRPCStdio + Health
   (service name = "plugin") + reflection + each user plugin.
6. Build ``grpclib.server.Server`` and start it on the listener.
7. Emit the handshake line to stdout, flush.
8. Block until ``GRPCController.Shutdown`` fires or SIGTERM is received.

``serve()`` is sync from the caller's perspective; it spins up its own
asyncio event loop. Plugin authors implement async servicers but call
``serve(config)`` from a normal ``main()``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import ssl
import sys
from dataclasses import dataclass, field
from typing import Optional, Union

from grpclib.reflection.service import ServerReflection
from grpclib.server import Server

from . import mtls, transport
from .broker import TLSMaterial, make_server_side_broker
from .controller import GRPCControllerServicer
from .cookie import validate_or_exit
from .health import StaticHealth
from .handshake import (
    HandshakeConfig,
    PROTOCOL_GRPC,
    format_line,
)
from .plugin import Plugin, PluginSet, VersionedPlugins
from .stdio import GRPCStdioServicer

GRPC_HEALTH_SERVICE_NAME = "plugin"  # what the go-plugin host pings
ENV_CLIENT_CERT = "PLUGIN_CLIENT_CERT"
ENV_PROTOCOL_VERSIONS = "PLUGIN_PROTOCOL_VERSIONS"
ENV_MULTIPLEX_GRPC = "PLUGIN_MULTIPLEX_GRPC"


@dataclass
class ServeConfig:
    """Configuration handed to :func:`serve`."""
    handshake_config: HandshakeConfig
    plugins: Union[PluginSet, VersionedPlugins]
    logger: Optional[logging.Logger] = None
    test_mode: bool = False
    force_tcp: bool = False
    grpc_options: list = field(default_factory=list)


def _is_versioned(p: Union[PluginSet, VersionedPlugins]) -> bool:
    if not p:
        return False
    return all(isinstance(k, int) for k in p.keys())


def _negotiate_version(cfg: ServeConfig) -> tuple[int, PluginSet]:
    """Pick (version, PluginSet) — mirrors go-plugin's protocolVersion()."""
    versioned: dict[int, PluginSet] = {}
    if _is_versioned(cfg.plugins):
        versioned.update(cfg.plugins)  # type: ignore[arg-type]
    else:
        versioned[cfg.handshake_config.protocol_version] = cfg.plugins  # type: ignore[assignment]

    client_versions: list[int] = []
    raw = os.environ.get(ENV_PROTOCOL_VERSIONS, "")
    for s in (p for p in raw.split(",") if p):
        try:
            client_versions.append(int(s))
        except ValueError:
            sys.stderr.write(f"server sent invalid plugin version {s!r}\n")

    server_versions = sorted(versioned.keys(), reverse=True)
    for v in server_versions:
        if v in client_versions:
            return v, versioned[v]

    fallback = sorted(versioned.keys())[0]
    return fallback, versioned[fallback]


async def _serve_async(config: ServeConfig) -> None:
    logger = config.logger or logging.getLogger("pyplugin.server")

    proto_version, plugin_set = _negotiate_version(config)
    listener = transport.open_listener(force_tcp=config.force_tcp)

    # AutoMTLS — match server.go: read PLUGIN_CLIENT_CERT, generate our cert,
    # trust the host's cert as both client CA and root.
    server_cert_b64 = ""
    server_ssl: Optional[ssl.SSLContext] = None
    server_cert: Optional[mtls.Cert] = None
    client_cert_pem = os.environ.get(ENV_CLIENT_CERT)
    if client_cert_pem:
        server_cert = mtls.generate()
        server_cert_b64 = mtls.encode_handshake_cert(server_cert.cert_der)
        server_ssl = mtls.server_ssl_context(
            cert_pem=server_cert.cert_pem,
            key_pem=server_cert.key_pem,
            peer_cert_pem=client_cert_pem.encode(),
        )

    # Build the broker's servicer + facade; the demux task we'll start under
    # this same event loop.
    broker_tls: Optional[TLSMaterial] = None
    if server_cert is not None and client_cert_pem:
        broker_tls = TLSMaterial(
            cert_pem=server_cert.cert_pem,
            key_pem=server_cert.key_pem,
            peer_cert_pem=client_cert_pem.encode(),
        )
    broker_servicer, broker, demux_task = make_server_side_broker(broker_tls)

    controller = GRPCControllerServicer()
    stdio_servicer = GRPCStdioServicer()
    health = StaticHealth()

    user_servicers: list = []
    for name, p in plugin_set.items():
        if not isinstance(p, Plugin):
            raise TypeError(f"plugin {name!r} must be a pyplugin.Plugin instance")
        user_servicers.extend(p.servicers(broker))

    base_servicers: list = [
        broker_servicer,
        controller,
        stdio_servicer,
        health,
    ] + user_servicers

    # Reflection extends the servicer list with its own service.
    all_servicers = ServerReflection.extend(base_servicers)

    server = Server(all_servicers)
    if listener.network == "unix":
        await server.start(path=listener.address, ssl=server_ssl)
    else:
        host, port = listener.address.split(":")
        await server.start(host=host, port=int(port), ssl=server_ssl)

    # Emit handshake. go-plugin always emits 6 segments; if PLUGIN_MULTIPLEX_GRPC
    # is set, the 7th tells the host whether we *support* mux. We don't, so we
    # advertise false (opt-out) — the host will then fail loudly if it required it.
    multiplex: Optional[bool] = None
    if os.environ.get(ENV_MULTIPLEX_GRPC):
        multiplex = False
    line = format_line(
        app_protocol_version=proto_version,
        network=listener.network,
        address=listener.address,
        protocol=PROTOCOL_GRPC,
        server_cert=server_cert_b64,
        multiplex_supported=multiplex,
    )
    if not config.test_mode:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    # Suppress SIGINT — go-plugin "eats" interrupts so the host owns shutdown.
    # SIGTERM still triggers shutdown via the signal handler below.
    loop = asyncio.get_running_loop()
    if not config.test_mode:
        try:
            loop.add_signal_handler(signal.SIGINT, lambda: None)
            loop.add_signal_handler(signal.SIGTERM, controller.shutdown_event.set)
        except (NotImplementedError, RuntimeError):
            pass  # Windows / non-main thread — best effort

    try:
        await controller.shutdown_event.wait()
    finally:
        # GracefulStop the gRPC server, then unlink the unix socket.
        server.close()
        try:
            await asyncio.wait_for(server.wait_closed(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
        await broker.close()
        stdio_servicer.close()
        demux_task.cancel()
        if listener.cleanup_path and os.path.exists(listener.cleanup_path):
            try:
                os.remove(listener.cleanup_path)
            except OSError:
                pass


def serve(config: ServeConfig) -> None:
    """Run the plugin server (sync entry point). Plugin's ``main()`` calls this."""
    if not config.test_mode:
        validate_or_exit(config.handshake_config)
    asyncio.run(_serve_async(config))
