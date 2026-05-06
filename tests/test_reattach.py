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


def _spawn(auto_mtls: bool) -> Client:
    c = Client(ClientConfig(
        handshake_config=HANDSHAKE,
        plugins={"kv": KVPlugin()},
        cmd=[sys.executable, str(PLUGIN_MAIN)],
        auto_mtls=auto_mtls,
        env=dict(os.environ),
    ))
    c.start()
    return c


@pytest.mark.parametrize("auto_mtls", [False, True])
def test_reattach(auto_mtls):
    primary = _spawn(auto_mtls)
    try:
        # Write something so we can verify state via the second client.
        primary.dispense("kv").Put(kv_pb2.PutRequest(key="rk", value=b"rv"))

        rc = primary.reattach_config()
        assert rc is not None and rc.pid > 0

        secondary = Client(ClientConfig(
            handshake_config=HANDSHAKE,
            plugins={"kv": KVPlugin()},
            reattach=rc,
            auto_mtls=auto_mtls,
        ))
        secondary.start()
        try:
            kv = secondary.dispense("kv")
            assert kv.Get(kv_pb2.GetRequest(key="rk")).value == b"rv"
        finally:
            # secondary.kill() shouldn't actually stop the process if it's
            # the same one as primary — but our impl will, so call only on
            # primary. We close the channel manually instead.
            if secondary._channel is not None:
                secondary._channel.close()
    finally:
        primary.kill()
