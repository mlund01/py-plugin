"""Host-side ``Client`` — spawns a plugin, performs handshake, dispenses stubs.

Mirrors go-plugin's ``Client`` (client.go) plus ``GRPCClient`` (grpc_client.go):

* ``start()`` spawns the subprocess, sets cookie + AutoMTLS env vars, reads
  the handshake line from stdout (with ``start_timeout``), validates it,
  dials the gRPC channel, and pings the health service.
* ``dispense(name)`` builds and returns a typed stub via ``Plugin.grpc_client``.
* ``kill()`` walks the shutdown ladder: GRPCController.Shutdown RPC → wait
  ``kill_timeout`` for clean exit → SIGTERM → wait → SIGKILL.

Reattach: if a ``ReattachConfig`` is supplied instead of ``cmd``, ``start()``
skips the spawn and goes straight to the dial.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence, Union

import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc

from . import logging_bridge, mtls, process, transport
from ._generated import grpc_controller_pb2, grpc_controller_pb2_grpc
from .broker import GRPCBroker, make_client_side_broker
from .errors import (
    AppProtocolMismatch,
    HandshakeError,
    ProcessExitedError,
    StartTimeout,
    UnsupportedProtocol,
)
from .handshake import (
    HandshakeConfig,
    HandshakeLine,
    PROTOCOL_GRPC,
    parse_line,
)
from .plugin import Plugin, PluginSet, VersionedPlugins
from .reattach import ReattachConfig
from .server import ENV_CLIENT_CERT, ENV_PROTOCOL_VERSIONS, GRPC_HEALTH_SERVICE_NAME
from .transport import ENV_MAX_PORT, ENV_MIN_PORT


@dataclass
class ClientConfig:
    handshake_config: HandshakeConfig
    plugins: Union[PluginSet, VersionedPlugins]
    cmd: Optional[Sequence[str]] = None
    reattach: Optional[ReattachConfig] = None
    auto_mtls: bool = True
    start_timeout: float = 60.0
    kill_timeout: float = 2.0
    logger: Optional[logging.Logger] = None
    stderr_logger: Optional[logging.Logger] = None
    env: Optional[Mapping[str, str]] = None
    cwd: Optional[str] = None
    skip_host_env: bool = False
    min_port: int = 10000
    max_port: int = 25000
    grpc_options: list = field(default_factory=list)


def _is_versioned(p: Union[PluginSet, VersionedPlugins]) -> bool:
    if not p:
        return False
    return all(isinstance(k, int) for k in p.keys())


class Client:
    """A handle on a running plugin subprocess (or reattached process)."""

    def __init__(self, config: ClientConfig) -> None:
        if (config.cmd is None) == (config.reattach is None):
            raise ValueError("exactly one of `cmd` or `reattach` must be set")
        self._cfg = config
        self._logger = config.logger or logging.getLogger("pyplugin.client")
        self._stderr_logger = config.stderr_logger or self._logger.getChild("stderr")
        self._proc: Optional[subprocess.Popen] = None
        self._handshake: Optional[HandshakeLine] = None
        self._channel: Optional[grpc.Channel] = None
        self._broker: Optional[GRPCBroker] = None
        self._broker_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._negotiated_version: int = 0
        self._plugin_set: PluginSet = {}
        self._tls: Optional[dict[str, bytes]] = None  # populated when AutoMTLS
        self._exited = threading.Event()
        self._killed = False
        self._lock = threading.Lock()

    # ----- public API -----

    def start(self) -> None:
        with self._lock:
            if self._channel is not None:
                return
            if self._cfg.reattach is not None:
                self._reattach()
            else:
                self._spawn_and_handshake()
            self._dial()

    def dispense(self, name: str) -> Any:
        self.start()
        if name not in self._plugin_set:
            raise KeyError(f"unknown plugin: {name!r}")
        plug = self._plugin_set[name]
        return plug.grpc_client(self._broker, self._channel)  # type: ignore[arg-type]

    @property
    def broker(self) -> GRPCBroker:
        self.start()
        assert self._broker is not None
        return self._broker

    @property
    def negotiated_version(self) -> int:
        return self._negotiated_version

    @property
    def pid(self) -> int | None:
        if self._proc is not None:
            return self._proc.pid
        if self._cfg.reattach is not None:
            return self._cfg.reattach.pid
        return None

    def reattach_config(self) -> ReattachConfig | None:
        if self._handshake is None:
            return None
        # Reattach inherits the ORIGINAL handshake/cert.
        cert_b64 = self._handshake.server_cert
        server_cert_pem = (
            mtls.der_to_pem(mtls.decode_handshake_cert(cert_b64)) if cert_b64 else None
        )
        client_cert = self._tls["cert_pem"] if self._tls else None
        client_key = self._tls["key_pem"] if self._tls else None
        return ReattachConfig(
            pid=self.pid or 0,
            addr=self._handshake.address,
            network=self._handshake.network,
            protocol=self._handshake.protocol,
            protocol_version=self._negotiated_version,
            server_cert_pem=server_cert_pem,
            client_cert_pem=client_cert,
            client_key_pem=client_key,
        )

    def kill(self) -> None:
        """Walk the shutdown ladder: Shutdown RPC → SIGTERM → SIGKILL."""
        if self._killed:
            return
        self._killed = True
        graceful = False
        if self._channel is not None:
            try:
                stub = grpc_controller_pb2_grpc.GRPCControllerStub(self._channel)
                stub.Shutdown(grpc_controller_pb2.Empty(), timeout=2.0)
                graceful = True
            except grpc.RpcError as e:
                self._logger.debug("controller.Shutdown failed", exc_info=e)
            try:
                self._channel.close()
            except Exception:  # noqa: BLE001
                pass
            self._channel = None
        if self._broker is not None:
            try:
                self._broker.close()
            except Exception:  # noqa: BLE001
                pass
            self._broker = None

        if self._cfg.reattach is not None and self._cfg.reattach.test:
            return  # test-mode: never kill

        if self._proc is None:
            return

        deadline = time.monotonic() + self._cfg.kill_timeout
        if graceful:
            while time.monotonic() < deadline and self._proc.poll() is None:
                time.sleep(0.05)

        if self._proc.poll() is None:
            self._logger.warning("plugin failed to exit gracefully — sending SIGTERM")
            process.terminate(self._proc)
            deadline = time.monotonic() + self._cfg.kill_timeout
            while time.monotonic() < deadline and self._proc.poll() is None:
                time.sleep(0.05)

        if self._proc.poll() is None:
            self._logger.error("plugin still alive after SIGTERM — sending SIGKILL")
            process.kill(self._proc)
            try:
                self._proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass

        self._exited.set()

    def __enter__(self) -> "Client":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.kill()

    # ----- internals -----

    def _build_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        if not self._cfg.skip_host_env:
            env.update(os.environ)
        if self._cfg.env:
            env.update(self._cfg.env)

        cookie = self._cfg.handshake_config
        env[cookie.magic_cookie_key] = cookie.magic_cookie_value

        # Versioned plugins → advertise all versions we know.
        if _is_versioned(self._cfg.plugins):
            versions = sorted(self._cfg.plugins.keys())  # type: ignore[arg-type]
        else:
            versions = [cookie.protocol_version]
        env[ENV_PROTOCOL_VERSIONS] = ",".join(str(v) for v in versions)

        env[ENV_MIN_PORT] = str(self._cfg.min_port)
        env[ENV_MAX_PORT] = str(self._cfg.max_port)

        if self._cfg.auto_mtls:
            host_cert = mtls.generate()
            self._tls = {
                "cert_pem": host_cert.cert_pem,
                "key_pem": host_cert.key_pem,
                "cert_der": host_cert.cert_der,
            }
            env[ENV_CLIENT_CERT] = host_cert.cert_pem.decode()

        return env

    def _spawn_and_handshake(self) -> None:
        env = self._build_env()
        assert self._cfg.cmd is not None
        self._proc = process.spawn(self._cfg.cmd, env=env, cwd=self._cfg.cwd)

        # Stderr-forwarder thread.
        stderr = self._proc.stderr
        assert stderr is not None
        self._stderr_thread = threading.Thread(
            target=self._forward_stderr, args=(stderr,), name="plugin-stderr",
            daemon=True,
        )
        self._stderr_thread.start()

        line = self._read_handshake_line()
        self._handshake = parse_line(line)
        self._validate_handshake(self._handshake)

    def _read_handshake_line(self) -> str:
        assert self._proc is not None
        stdout = self._proc.stdout
        assert stdout is not None
        line_holder: dict[str, str] = {}
        err_holder: dict[str, BaseException] = {}

        def reader() -> None:
            try:
                raw = stdout.readline()
                if not raw:
                    err_holder["e"] = ProcessExitedError(
                        "plugin exited before sending handshake")
                    return
                line_holder["line"] = raw.decode("utf-8", errors="replace").strip()
            except Exception as e:  # noqa: BLE001
                err_holder["e"] = e

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        t.join(timeout=self._cfg.start_timeout)
        if t.is_alive():
            self._proc.kill()
            raise StartTimeout(
                f"plugin did not emit a handshake within {self._cfg.start_timeout}s")
        if "e" in err_holder:
            raise err_holder["e"]
        return line_holder["line"]

    def _validate_handshake(self, h: HandshakeLine) -> None:
        # Negotiate plugin set.
        if _is_versioned(self._cfg.plugins):
            versioned: dict[int, PluginSet] = self._cfg.plugins  # type: ignore[assignment]
            if h.app_protocol_version not in versioned:
                raise AppProtocolMismatch(
                    f"plugin advertised version {h.app_protocol_version}; "
                    f"client supports {sorted(versioned.keys())}"
                )
            self._plugin_set = versioned[h.app_protocol_version]
        else:
            cfg_v = self._cfg.handshake_config.protocol_version
            if h.app_protocol_version != cfg_v:
                raise AppProtocolMismatch(
                    f"plugin advertised version {h.app_protocol_version}; "
                    f"client expects {cfg_v}"
                )
            self._plugin_set = self._cfg.plugins  # type: ignore[assignment]

        if h.protocol != PROTOCOL_GRPC:
            raise UnsupportedProtocol(
                f"plugin advertised protocol {h.protocol!r}; pyplugin only supports 'grpc'")

        self._negotiated_version = h.app_protocol_version

    def _reattach(self) -> None:
        r = self._cfg.reattach
        assert r is not None
        # Synthesize a HandshakeLine for downstream code.
        cert_b64 = ""
        if r.server_cert_pem is not None:
            from cryptography import x509
            from cryptography.hazmat.primitives import serialization
            cert = x509.load_pem_x509_certificate(r.server_cert_pem)
            cert_b64 = mtls.encode_handshake_cert(cert.public_bytes(serialization.Encoding.DER))
        self._handshake = HandshakeLine(
            core_protocol_version=1,
            app_protocol_version=r.protocol_version,
            network=r.network,
            address=r.addr,
            protocol=r.protocol,
            server_cert=cert_b64,
        )
        self._negotiated_version = r.protocol_version
        if _is_versioned(self._cfg.plugins):
            versioned: dict[int, PluginSet] = self._cfg.plugins  # type: ignore[assignment]
            self._plugin_set = versioned.get(r.protocol_version, {})
        else:
            self._plugin_set = self._cfg.plugins  # type: ignore[assignment]

        if r.client_cert_pem and r.client_key_pem:
            self._tls = {
                "cert_pem": r.client_cert_pem,
                "key_pem": r.client_key_pem,
                "cert_der": b"",
            }

    def _dial(self) -> None:
        h = self._handshake
        assert h is not None
        target = transport.grpc_dial_target(h.network, h.address)

        if h.server_cert and self._tls is not None:
            server_cert_der = mtls.decode_handshake_cert(h.server_cert)
            server_cert_pem = mtls.der_to_pem(server_cert_der)
            creds = grpc.ssl_channel_credentials(
                root_certificates=server_cert_pem,
                private_key=self._tls["key_pem"],
                certificate_chain=self._tls["cert_pem"],
            )
            options = list(self._cfg.grpc_options) + [
                ("grpc.ssl_target_name_override", "localhost"),
            ]
            self._channel = grpc.secure_channel(target, creds, options=options)
            # Configure broker tls so brokered sub-channels also use mTLS.
            self._channel_tls = {
                "root": server_cert_pem,
                "client_cert": self._tls["cert_pem"],
                "client_key": self._tls["key_pem"],
            }
        elif h.server_cert and self._tls is None:
            raise HandshakeError(
                "plugin advertised AutoMTLS but client wasn't configured for it")
        else:
            self._channel = grpc.insecure_channel(target, options=self._cfg.grpc_options)
            self._channel_tls = None

        # Health check — match go-plugin's ping (Service: "plugin").
        deadline = time.monotonic() + min(self._cfg.start_timeout, 30.0)
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            try:
                hstub = health_pb2_grpc.HealthStub(self._channel)
                resp = hstub.Check(
                    health_pb2.HealthCheckRequest(service=GRPC_HEALTH_SERVICE_NAME),
                    timeout=2.0,
                )
                if resp.status == health_pb2.HealthCheckResponse.SERVING:
                    last_err = None
                    break
                last_err = HandshakeError(f"plugin health = {resp.status}")
            except grpc.RpcError as e:
                last_err = e
                time.sleep(0.05)
        if last_err is not None:
            raise HandshakeError(f"plugin health check failed: {last_err}")

        # Start broker.
        self._broker, self._broker_thread = make_client_side_broker(self._channel)
        if self._channel_tls is not None:
            self._broker.configure_tls(
                root_cert_pem=self._channel_tls["root"],
                client_cert_pem=self._channel_tls["client_cert"],
                client_key_pem=self._channel_tls["client_key"],
            )
        self._broker_thread.start()

    def _forward_stderr(self, stream) -> None:
        try:
            for raw in iter(stream.readline, b""):
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip()
                if line:
                    logging_bridge.emit(self._stderr_logger, line)
        except Exception:  # noqa: BLE001
            return
