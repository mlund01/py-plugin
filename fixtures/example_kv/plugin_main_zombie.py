"""Plugin variant that ignores BOTH Shutdown and SIGTERM — must reach SIGKILL."""
from __future__ import annotations

import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from pyplugin import ServeConfig  # noqa: E402
from pyplugin.controller import GRPCControllerServicer  # noqa: E402
from fixtures.example_kv.kv_plugin import HANDSHAKE, KVPlugin  # noqa: E402


def main() -> None:
    def ignore(self, request, context):
        from pyplugin._generated import grpc_controller_pb2
        return grpc_controller_pb2.Empty()

    GRPCControllerServicer.Shutdown = ignore

    # Ignore SIGTERM so the host has to escalate to SIGKILL.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

    from pyplugin import serve
    serve(ServeConfig(handshake_config=HANDSHAKE, plugins={"kv": KVPlugin()}))


if __name__ == "__main__":
    main()
