"""Plugin variant that ignores GRPCController.Shutdown — host must escalate to SIGTERM."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from pyplugin import ServeConfig  # noqa: E402
from pyplugin.controller import GRPCControllerServicer  # noqa: E402
from fixtures.example_kv.kv_plugin import HANDSHAKE, KVPlugin  # noqa: E402


def main() -> None:
    # Override Shutdown to NOT set the shutdown_event.
    async def ignore(self, stream):
        from pyplugin._generated import grpc_controller_pb2
        await stream.recv_message()
        await stream.send_message(grpc_controller_pb2.Empty())

    GRPCControllerServicer.Shutdown = ignore

    from pyplugin import serve
    serve(ServeConfig(handshake_config=HANDSHAKE, plugins={"kv": KVPlugin()}))


if __name__ == "__main__":
    main()
