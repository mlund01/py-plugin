"""Plugin entry point. The host launches this script as a subprocess.

Run:
    python -m examples.greeter.plugin
(or any equivalent that puts the project root on sys.path).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running directly: ``python examples/greeter/plugin.py`` from the repo root.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from pyplugin import ServeConfig, serve  # noqa: E402
from examples.greeter.shared import HANDSHAKE, GreeterPlugin  # noqa: E402


def main() -> None:
    serve(ServeConfig(
        handshake_config=HANDSHAKE,
        plugins={"greeter": GreeterPlugin()},
    ))


if __name__ == "__main__":
    main()
