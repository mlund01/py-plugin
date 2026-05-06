"""End-to-end smoke tests for the Greeter/KV plugin."""
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


def _client(*, auto_mtls: bool = False, force_tcp: bool = False) -> Client:
    env = dict(os.environ)
    if force_tcp:
        env["PLUGIN_FORCE_TCP"] = "1"
    return Client(ClientConfig(
        handshake_config=HANDSHAKE,
        plugins={"kv": KVPlugin()},
        cmd=[sys.executable, str(PLUGIN_MAIN)],
        auto_mtls=auto_mtls,
        env=env,
        kill_timeout=2.0,
        start_timeout=15.0,
    ))


def _round_trip(stub) -> None:
    stub.Put(kv_pb2.PutRequest(key="hello", value=b"world"))
    resp = stub.Get(kv_pb2.GetRequest(key="hello"))
    assert resp.value == b"world"


def test_unix_socket_no_mtls():
    with _client(auto_mtls=False) as c:
        kv = c.dispense("kv")
        _round_trip(kv)


def test_auto_mtls():
    with _client(auto_mtls=True) as c:
        kv = c.dispense("kv")
        _round_trip(kv)


def test_kill_terminates_process():
    c = _client(auto_mtls=False)
    c.start()
    pid = c.pid
    assert pid is not None
    c.kill()
    # Allow up to a few seconds for the OS to reap.
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    pytest.fail(f"plugin pid {pid} still alive after kill()")
