"""End-to-end smoke tests for the KV plugin (Python ↔ Python, async)."""
from __future__ import annotations

import os
import pathlib
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN_MAIN = ROOT / "fixtures" / "example_kv" / "plugin_main.py"

from pyplugin import Client, ClientConfig  # noqa: E402
from fixtures.example_kv.kv_plugin import HANDSHAKE, KVPlugin  # noqa: E402
from fixtures.example_kv.generated import kv_pb2  # noqa: E402


def _client(*, auto_mtls: bool = False) -> Client:
    return Client(ClientConfig(
        handshake_config=HANDSHAKE,
        plugins={"kv": KVPlugin()},
        cmd=[sys.executable, str(PLUGIN_MAIN)],
        auto_mtls=auto_mtls,
        env=dict(os.environ),
        kill_timeout=2.0,
        start_timeout=15.0,
    ))


async def _round_trip(stub) -> None:
    await stub.Put(kv_pb2.PutRequest(key="hello", value=b"world"))
    resp = await stub.Get(kv_pb2.GetRequest(key="hello"))
    assert resp.value == b"world"


async def test_unix_socket_no_mtls():
    async with _client(auto_mtls=False) as c:
        kv = c.dispense("kv")
        await _round_trip(kv)


async def test_auto_mtls_p521():
    async with _client(auto_mtls=True) as c:
        kv = c.dispense("kv")
        await _round_trip(kv)


async def test_kill_terminates_process():
    c = _client(auto_mtls=False)
    await c.start()
    pid = c.pid
    assert pid is not None
    await c.kill()
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    pytest.fail(f"plugin pid {pid} still alive after kill()")
