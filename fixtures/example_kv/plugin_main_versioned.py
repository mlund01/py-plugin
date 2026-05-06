"""Plugin variant that advertises multiple protocol versions (for negotiation tests)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from pyplugin import HandshakeConfig, ServeConfig, serve  # noqa: E402
from fixtures.example_kv.kv_plugin import HANDSHAKE, KVPlugin  # noqa: E402


def main() -> None:
    # Plugin supports versions 2 and 3. Host can pick whichever overlaps.
    serve(ServeConfig(
        handshake_config=HandshakeConfig(
            protocol_version=2,
            magic_cookie_key=HANDSHAKE.magic_cookie_key,
            magic_cookie_value=HANDSHAKE.magic_cookie_value,
        ),
        plugins={
            2: {"kv": KVPlugin()},
            3: {"kv": KVPlugin()},
        },
    ))


if __name__ == "__main__":
    main()
