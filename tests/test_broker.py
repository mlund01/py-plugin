"""Broker round-trip: plugin calls back into the host via the broker (async)."""
from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN_MAIN = ROOT / "fixtures" / "example_kv" / "plugin_main.py"

from pyplugin import Client, ClientConfig  # noqa: E402
from fixtures.example_kv.kv_plugin import HANDSHAKE, KVPlugin  # noqa: E402
from fixtures.example_kv.generated import (  # noqa: E402
    callback_grpc,
    callback_pb2,
    kv_pb2,
)


class CallbackImpl(callback_grpc.CallbackBase):
    def __init__(self) -> None:
        self.seen: list[str] = []

    async def Notify(self, stream) -> None:
        request = await stream.recv_message()
        self.seen.append(request.note)
        await stream.send_message(callback_pb2.NotifyResponse(echo=f"ack:{request.note}"))


async def _run_test(*, auto_mtls: bool) -> None:
    impl = CallbackImpl()
    c = Client(ClientConfig(
        handshake_config=HANDSHAKE,
        plugins={"kv": KVPlugin()},
        cmd=[sys.executable, str(PLUGIN_MAIN)],
        auto_mtls=auto_mtls,
        env=dict(os.environ),
    ))
    async with c:
        broker = c.broker
        sid = broker.next_id()
        srv = await broker.accept_and_serve(sid, [impl])
        try:
            kv = c.dispense("kv")
            resp = await kv.PingHost(kv_pb2.PingHostRequest(broker_id=sid, note="howdy"))
            assert resp.echo == "ack:howdy"
            assert impl.seen == ["howdy"]
        finally:
            srv.close()
            try:
                await srv.wait_closed()
            except Exception:  # noqa: BLE001
                pass


async def test_broker_no_mtls():
    await _run_test(auto_mtls=False)


async def test_broker_with_mtls():
    await _run_test(auto_mtls=True)
