"""Plugin entry point that registers under the name ``kv_grpc`` to match
go-plugin's example PluginMap (``shared.PluginGRPC = "kv_grpc"``).

This lets a Go host built against go-plugin's example launch our Python
plugin and dispense it as the KV interface.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from pyplugin import ServeConfig, serve  # noqa: E402
from fixtures.example_kv.kv_plugin import HANDSHAKE, KVPlugin  # noqa: E402


def main() -> None:
    serve(ServeConfig(
        handshake_config=HANDSHAKE,
        plugins={"kv_grpc": KVPlugin()},  # name matches go-plugin example
    ))


if __name__ == "__main__":
    main()
