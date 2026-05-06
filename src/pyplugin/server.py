"""Plugin-side ``serve()`` entry point.

Mirrors go-plugin's ``Serve(opts *ServeConfig)``:

1. Validate magic cookie (or skip in test mode).
2. Negotiate the protocol version against ``PLUGIN_PROTOCOL_VERSIONS``.
3. Open a listener (unix on POSIX, TCP on Windows).
4. Build a gRPC server, with mTLS if ``PLUGIN_CLIENT_CERT`` is set.
5. Register: grpc.health (service name = "plugin"), reflection, GRPCBroker,
   GRPCController, GRPCStdio, then each user plugin via ``Plugin.grpc_server``.
6. Emit the handshake line to stdout, flush.
7. Block until the controller's ``Shutdown`` event fires (or ``SIGINT/SIGTERM``).
"""
from __future__ import annotations

import logging
import os
import signal
import sys
from concurrent import futures
from dataclasses import dataclass, field
from typing import Mapping, Optional, Union

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection

from . import mtls, transport
from ._generated import (
    grpc_broker_pb2_grpc,
    grpc_controller_pb2_grpc,
    grpc_stdio_pb2_grpc,
)
from .broker import make_server_side_broker
from .controller import GRPCControllerServicer
from .cookie import validate_or_exit
from .stdio import GRPCStdioServicer
from .handshake import (
    HandshakeConfig,
    PROTOCOL_GRPC,
    format_line,
)
from .plugin import Plugin, PluginSet, VersionedPlugins

GRPC_HEALTH_SERVICE_NAME = "plugin"  # what go-plugin's host pings — must match
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
    grpc_max_workers: int = 64
    force_tcp: bool = False
    grpc_options: list = field(default_factory=list)


def _negotiate_version(cfg: ServeConfig) -> tuple[int, PluginSet]:
    """Pick (version, PluginSet) — mirroring go-plugin's protocolVersion()."""
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

    # No overlap — return the lowest server version so the client can produce
    # a friendly error (matches go-plugin).
    fallback = sorted(versioned.keys())[0]
    return fallback, versioned[fallback]


def _is_versioned(p: Union[PluginSet, VersionedPlugins]) -> bool:
    if not p:
        return False
    return all(isinstance(k, int) for k in p.keys())


def serve(config: ServeConfig) -> None:
    """Run the plugin server. Blocks until shutdown. Plugin's ``main()`` calls this."""
    if not config.test_mode:
        validate_or_exit(config.handshake_config)

    logger = config.logger or logging.getLogger("pyplugin.server")
    proto_version, plugin_set = _negotiate_version(config)

    listener = transport.open_listener(force_tcp=config.force_tcp)

    # AutoMTLS — match server.go: read PLUGIN_CLIENT_CERT, generate our cert,
    # trust the host's cert as both client CA and root.
    server_cert_b64 = ""
    server_credentials: Optional[grpc.ServerCredentials] = None
    server_cert_obj: Optional[mtls.Cert] = None
    client_cert_pem = os.environ.get(ENV_CLIENT_CERT)
    if client_cert_pem:
        server_cert_obj = mtls.generate()
        server_cert_b64 = mtls.encode_handshake_cert(server_cert_obj.cert_der)
        server_credentials = grpc.ssl_server_credentials(
            [(server_cert_obj.key_pem, server_cert_obj.cert_pem)],
            root_certificates=client_cert_pem.encode(),
            require_client_auth=True,
        )

    # Build gRPC server.
    grpc_server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=config.grpc_max_workers),
        options=config.grpc_options,
    )
    if server_credentials is not None:
        grpc_server.add_secure_port(listener.grpc_target, server_credentials)
    else:
        grpc_server.add_insecure_port(listener.grpc_target)

    # Health check — go-plugin's host pings the "plugin" service.
    health_servicer = health.HealthServicer()
    health_servicer.set(GRPC_HEALTH_SERVICE_NAME, health_pb2.HealthCheckResponse.SERVING)
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, grpc_server)

    # Broker + controller + (later) stdio.
    broker_servicer, broker, demux_thread = make_server_side_broker()
    if server_cert_obj is not None and client_cert_pem:
        broker.configure_tls(
            root_cert_pem=client_cert_pem.encode(),
            client_cert_pem=server_cert_obj.cert_pem,
            client_key_pem=server_cert_obj.key_pem,
        )
    grpc_broker_pb2_grpc.add_GRPCBrokerServicer_to_server(broker_servicer, grpc_server)
    demux_thread.start()

    controller = GRPCControllerServicer()
    grpc_controller_pb2_grpc.add_GRPCControllerServicer_to_server(controller, grpc_server)

    stdio_servicer = GRPCStdioServicer()
    grpc_stdio_pb2_grpc.add_GRPCStdioServicer_to_server(stdio_servicer, grpc_server)

    # Register user plugins.
    service_names: list[str] = [
        health_pb2.DESCRIPTOR.services_by_name["Health"].full_name,
        "plugin.GRPCBroker",
        "plugin.GRPCController",
        "plugin.GRPCStdio",
    ]
    for name, p in plugin_set.items():
        if not isinstance(p, Plugin):
            raise TypeError(f"plugin {name!r} must be a pyplugin.Plugin instance")
        p.grpc_server(broker, grpc_server)

    # Reflection (covers user plugins because we register after them).
    try:
        reflection.enable_server_reflection(service_names, grpc_server)
    except Exception:  # noqa: BLE001 — reflection failure shouldn't kill the plugin
        logger.debug("reflection setup failed", exc_info=True)

    grpc_server.start()

    # Emit the handshake. Go-plugin always emits 6 segments; if the multiplex
    # env opt-in is present, append a 7th. We don't *implement* multiplex
    # for v1 but we still advertise truthfully (false).
    multiplex: Optional[bool] = None
    if os.environ.get(ENV_MULTIPLEX_GRPC):
        multiplex = False  # we don't yet support muxing the broker over the main socket
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

    # Suppress SIGINT — go-plugin "eats" interrupts so the host owns the
    # shutdown sequence. SIGTERM still terminates by default.
    if not config.test_mode:
        try:
            signal.signal(signal.SIGINT, signal.SIG_IGN)
        except (ValueError, OSError):
            pass

    try:
        controller.shutdown_event.wait()
    finally:
        # GracefulStop the gRPC server, then unlink unix socket if any.
        grpc_server.stop(grace=2.0).wait(timeout=5.0)
        broker.close()
        stdio_servicer.close()
        if listener.cleanup_path and os.path.exists(listener.cleanup_path):
            try:
                os.remove(listener.cleanup_path)
            except OSError:
                pass
