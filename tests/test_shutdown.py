"""Shutdown ladder: graceful / SIGTERM / SIGKILL."""
from __future__ import annotations

import os
import pathlib
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
GRACEFUL_PLUGIN = ROOT / "fixtures" / "example_kv" / "plugin_main.py"
STUBBORN_PLUGIN = ROOT / "fixtures" / "example_kv" / "plugin_main_stubborn.py"
ZOMBIE_PLUGIN = ROOT / "fixtures" / "example_kv" / "plugin_main_zombie.py"

from pyplugin import Client, ClientConfig  # noqa: E402
from fixtures.example_kv.kv_plugin import HANDSHAKE, KVPlugin  # noqa: E402


def _client(path: pathlib.Path, kill_timeout: float = 1.0) -> Client:
    return Client(ClientConfig(
        handshake_config=HANDSHAKE,
        plugins={"kv": KVPlugin()},
        cmd=[sys.executable, str(path)],
        auto_mtls=False,
        kill_timeout=kill_timeout,
        env=dict(os.environ),
    ))


def _await_dead(pid: int, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


async def test_graceful_shutdown():
    c = _client(GRACEFUL_PLUGIN)
    await c.start()
    pid = c.pid
    assert pid is not None
    await c.kill()
    assert _await_dead(pid)


async def test_stubborn_falls_back_to_sigterm():
    c = _client(STUBBORN_PLUGIN, kill_timeout=0.5)
    await c.start()
    pid = c.pid
    assert pid is not None
    await c.kill()
    assert _await_dead(pid)


@pytest.mark.skipif(sys.platform.startswith("win"), reason="SIGTERM-ignore not portable")
async def test_zombie_requires_sigkill():
    c = _client(ZOMBIE_PLUGIN, kill_timeout=0.5)
    await c.start()
    pid = c.pid
    assert pid is not None
    await c.kill()
    assert _await_dead(pid, timeout=5.0)
