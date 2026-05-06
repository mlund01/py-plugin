"""Real Python ↔ Go interop: a Python host launches go-plugin's example KV plugin
(a Go binary) and drives it over gRPC. Proves wire-compat byte-for-byte.

This test only runs if the binary at ``$PYPLUGIN_GO_PLUGIN_KV`` exists.
"""
from __future__ import annotations

import os
import pathlib
import sys
from typing import Any

import pytest
from grpclib.client import Channel

from pyplugin import Client, ClientConfig, HandshakeConfig, Plugin
from pyplugin.broker import GRPCBroker

# Reuse the example_kv stubs — go-plugin's example proto has the same package
# (``proto``), service (``KV``), and Get/Put messages, so the wire paths match
# byte-for-byte. (Our proto adds a ``PingHost`` method that the Go plugin doesn't
# implement; we don't call it in the interop tests.)
from fixtures.example_kv.generated import kv_grpc, kv_pb2


GO_PLUGIN = os.environ.get("PYPLUGIN_GO_PLUGIN_KV") or "/tmp/goplugin-interop/plugin-go-grpc"


# Match the Go example's HandshakeConfig (shared/interface.go).
HANDSHAKE = HandshakeConfig(
    protocol_version=1,
    magic_cookie_key="BASIC_PLUGIN",
    magic_cookie_value="hello",
)


class GoKVPlugin(Plugin):
    """Stub side only — we don't serve this plugin, we consume it.

    The plugin name in our PluginMap must match what the Go plugin registers.
    The Go example registers "kv" as the gRPC plugin name.
    """

    def servicers(self, broker: GRPCBroker) -> list:
        return []  # host-only, never serves

    def stub(self, broker: GRPCBroker, channel: Channel) -> Any:
        return kv_grpc.KVStub(channel)


@pytest.mark.skipif(not pathlib.Path(GO_PLUGIN).exists(),
                    reason=f"go plugin binary not found at {GO_PLUGIN}")
async def test_python_host_drives_go_plugin_no_mtls():
    c = Client(ClientConfig(
        handshake_config=HANDSHAKE,
        plugins={"kv": GoKVPlugin()},
        cmd=[GO_PLUGIN],
        auto_mtls=False,
        env=dict(os.environ),
    ))
    async with c:
        kv = c.dispense("kv")
        await kv.Put(kv_pb2.PutRequest(key="hello", value=b"from-python-host"))
        resp = await kv.Get(kv_pb2.GetRequest(key="hello"))
        # The Go plugin appends "\n\nWritten from plugin-go-grpc" to the value.
        assert b"from-python-host" in resp.value
        assert b"plugin-go-grpc" in resp.value


@pytest.mark.skipif(not pathlib.Path(GO_PLUGIN).exists(),
                    reason=f"go plugin binary not found at {GO_PLUGIN}")
async def test_python_host_drives_go_plugin_with_p521_automtls():
    c = Client(ClientConfig(
        handshake_config=HANDSHAKE,
        plugins={"kv": GoKVPlugin()},
        cmd=[GO_PLUGIN],
        auto_mtls=True,
        env=dict(os.environ),
    ))
    async with c:
        kv = c.dispense("kv")
        await kv.Put(kv_pb2.PutRequest(key="mtls-hello", value=b"p521-mtls-payload"))
        resp = await kv.Get(kv_pb2.GetRequest(key="mtls-hello"))
        assert b"p521-mtls-payload" in resp.value
