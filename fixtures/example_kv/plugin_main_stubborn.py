"""Plugin variant that ignores the GRPCController.Shutdown RPC.

Used to test the kill ladder: the host must escalate to SIGTERM. The plugin
*does* honor SIGTERM (Python's default), so this exercises step 2 of the
ladder.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from pyplugin import ServeConfig  # noqa: E402
from pyplugin.controller import GRPCControllerServicer  # noqa: E402
from fixtures.example_kv.kv_plugin import HANDSHAKE, KVPlugin  # noqa: E402


def main() -> None:
    # Monkey-patch the controller servicer so Shutdown becomes a no-op.
    original = GRPCControllerServicer.Shutdown

    def ignore(self, request, context):
        from pyplugin._generated import grpc_controller_pb2
        return grpc_controller_pb2.Empty()  # do NOT set shutdown_event

    GRPCControllerServicer.Shutdown = ignore

    from pyplugin import serve
    serve(ServeConfig(handshake_config=HANDSHAKE, plugins={"kv": KVPlugin()}))


if __name__ == "__main__":
    main()
