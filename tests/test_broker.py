"""Broker round-trip: plugin calls back into the host via the broker."""
from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN_MAIN = ROOT / "fixtures" / "example_kv" / "plugin_main.py"

from pyplugin import Client, ClientConfig  # noqa: E402
from fixtures.example_kv.kv_plugin import HANDSHAKE, KVPlugin  # noqa: E402
from fixtures.example_kv.generated import (  # noqa: E402
    callback_pb2,
    callback_pb2_grpc,
    kv_pb2,
)


class CallbackImpl(callback_pb2_grpc.CallbackServicer):
    def __init__(self) -> None:
        self.seen: list[str] = []

    def Notify(self, request, context):
        self.seen.append(request.note)
        return callback_pb2.NotifyResponse(echo=f"ack:{request.note}")


def _run_test(*, auto_mtls: bool) -> None:
    impl = CallbackImpl()
    c = Client(ClientConfig(
        handshake_config=HANDSHAKE,
        plugins={"kv": KVPlugin()},
        cmd=[sys.executable, str(PLUGIN_MAIN)],
        auto_mtls=auto_mtls,
        env=dict(os.environ),
    ))
    with c:
        broker = c.broker
        sid = broker.next_id()

        def register(server):
            callback_pb2_grpc.add_CallbackServicer_to_server(impl, server)

        srv = broker.accept_and_serve(sid, register)
        try:
            kv = c.dispense("kv")
            resp = kv.PingHost(kv_pb2.PingHostRequest(broker_id=sid, note="howdy"), timeout=5.0)
            assert resp.echo == "ack:howdy"
            assert impl.seen == ["howdy"]
        finally:
            srv.stop(0)


def test_broker_no_mtls():
    _run_test(auto_mtls=False)


def test_broker_with_mtls():
    _run_test(auto_mtls=True)
