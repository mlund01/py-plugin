"""VersionedPlugins negotiation."""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN_MAIN = ROOT / "fixtures" / "example_kv" / "plugin_main_versioned.py"

from pyplugin import Client, ClientConfig, HandshakeConfig  # noqa: E402
from pyplugin.errors import AppProtocolMismatch  # noqa: E402
from fixtures.example_kv.kv_plugin import HANDSHAKE, KVPlugin  # noqa: E402
from fixtures.example_kv.generated import kv_pb2  # noqa: E402


def test_picks_highest_overlap():
    # Plugin supports {2, 3}. Host advertises {1, 3}. They should agree on 3.
    c = Client(ClientConfig(
        handshake_config=HandshakeConfig(
            protocol_version=0,  # ignored when versioned plugins are set
            magic_cookie_key=HANDSHAKE.magic_cookie_key,
            magic_cookie_value=HANDSHAKE.magic_cookie_value,
        ),
        plugins={
            1: {"kv": KVPlugin()},
            3: {"kv": KVPlugin()},
        },
        cmd=[sys.executable, str(PLUGIN_MAIN)],
        auto_mtls=False,
        env=dict(os.environ),
    ))
    with c:
        assert c.negotiated_version == 3
        kv = c.dispense("kv")
        kv.Put(kv_pb2.PutRequest(key="k", value=b"v"))


def test_no_overlap_raises():
    # Plugin supports {2, 3}. Host advertises {7, 8}. No overlap → mismatch.
    c = Client(ClientConfig(
        handshake_config=HandshakeConfig(
            protocol_version=0,
            magic_cookie_key=HANDSHAKE.magic_cookie_key,
            magic_cookie_value=HANDSHAKE.magic_cookie_value,
        ),
        plugins={
            7: {"kv": KVPlugin()},
            8: {"kv": KVPlugin()},
        },
        cmd=[sys.executable, str(PLUGIN_MAIN)],
        auto_mtls=False,
        env=dict(os.environ),
    ))
    with pytest.raises(AppProtocolMismatch):
        c.start()
    c.kill()
