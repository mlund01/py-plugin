"""Host that launches the Greeter plugin and calls it.

Run:
    python examples/greeter/host.py [name]

Set AUTO_MTLS=1 in the environment to exercise the P-521 AutoMTLS path.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from pyplugin import Client, ClientConfig  # noqa: E402
from examples.greeter.generated import greeter_pb2  # noqa: E402
from examples.greeter.shared import HANDSHAKE, GreeterPlugin  # noqa: E402

PLUGIN_SCRIPT = ROOT / "examples" / "greeter" / "plugin.py"


async def main(name: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")

    auto_mtls = os.environ.get("AUTO_MTLS") == "1"

    config = ClientConfig(
        handshake_config=HANDSHAKE,
        plugins={"greeter": GreeterPlugin()},
        cmd=[sys.executable, str(PLUGIN_SCRIPT)],
        auto_mtls=auto_mtls,
    )

    print(f"launching plugin (auto_mtls={auto_mtls})...")
    async with Client(config) as client:
        greeter = client.dispense("greeter")

        greet_resp = await greeter.Greet(greeter_pb2.GreetRequest(name=name))
        print(f"  Greet: {greet_resp.message!r}")

        text = "the quick brown fox jumps over the lazy dog"
        count_resp = await greeter.Count(greeter_pb2.CountRequest(text=text))
        print(f"  Count({text!r}): letters={count_resp.letters}, words={count_resp.words}")


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "world"
    asyncio.run(main(name))
