"""Reattach: spawn a plugin, capture its ReattachConfig, reconnect via a second client."""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN_MAIN = ROOT / "fixtures" / "example_kv" / "plugin_main.py"

from pyplugin import Client, ClientConfig  # noqa: E402
from fixtures.example_kv.kv_plugin import HANDSHAKE, KVPlugin  # noqa: E402
from fixtures.example_kv.generated import kv_pb2  # noqa: E402


def _spawn_cfg(auto_mtls: bool) -> ClientConfig:
    return ClientConfig(
        handshake_config=HANDSHAKE,
        plugins={"kv": KVPlugin()},
        cmd=[sys.executable, str(PLUGIN_MAIN)],
        auto_mtls=auto_mtls,
        env=dict(os.environ),
    )


@pytest.mark.parametrize("auto_mtls", [False, True])
async def test_reattach(auto_mtls):
    primary = Client(_spawn_cfg(auto_mtls))
    try:
        await primary.start()
        kv = primary.dispense("kv")
        await kv.Put(kv_pb2.PutRequest(key="rk", value=b"rv"))

        rc = primary.reattach_config()
        assert rc is not None and rc.pid > 0

        secondary = Client(ClientConfig(
            handshake_config=HANDSHAKE,
            plugins={"kv": KVPlugin()},
            reattach=rc,
            auto_mtls=auto_mtls,
        ))
        await secondary.start()
        try:
            kv2 = secondary.dispense("kv")
            assert (await kv2.Get(kv_pb2.GetRequest(key="rk"))).value == b"rv"
        finally:
            if secondary._channel is not None:
                secondary._channel.close()
                secondary._channel = None
    finally:
        await primary.kill()
