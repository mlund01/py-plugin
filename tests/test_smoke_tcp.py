"""TCP-loopback smoke (the plugin process forces TCP via ServeConfig.force_tcp)."""
from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN_MAIN = ROOT / "fixtures" / "example_kv" / "plugin_main_tcp.py"

from pyplugin import Client, ClientConfig  # noqa: E402
from fixtures.example_kv.kv_plugin import HANDSHAKE, KVPlugin  # noqa: E402
from fixtures.example_kv.generated import kv_pb2  # noqa: E402


async def test_tcp_no_mtls():
    c = Client(ClientConfig(
        handshake_config=HANDSHAKE,
        plugins={"kv": KVPlugin()},
        cmd=[sys.executable, str(PLUGIN_MAIN)],
        auto_mtls=False,
        env=dict(os.environ),
    ))
    async with c:
        kv = c.dispense("kv")
        await kv.Put(kv_pb2.PutRequest(key="k", value=b"v"))
        assert (await kv.Get(kv_pb2.GetRequest(key="k"))).value == b"v"
        assert "127.0.0.1:" in c._handshake.address  # type: ignore[union-attr]


async def test_tcp_with_mtls_p521():
    c = Client(ClientConfig(
        handshake_config=HANDSHAKE,
        plugins={"kv": KVPlugin()},
        cmd=[sys.executable, str(PLUGIN_MAIN)],
        auto_mtls=True,
        env=dict(os.environ),
    ))
    async with c:
        kv = c.dispense("kv")
        await kv.Put(kv_pb2.PutRequest(key="k", value=b"v2"))
        assert (await kv.Get(kv_pb2.GetRequest(key="k"))).value == b"v2"
