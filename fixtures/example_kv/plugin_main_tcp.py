"""Plugin variant that forces TCP loopback even on POSIX (for the TCP smoke test)."""
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
        plugins={"kv": KVPlugin()},
        force_tcp=True,
    ))


if __name__ == "__main__":
    main()
