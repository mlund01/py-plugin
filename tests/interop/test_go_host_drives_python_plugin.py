"""Real Python ↔ Go interop, OTHER direction: a Go host (built against
``hashicorp/go-plugin``) launches a Python plugin built with ``pyplugin``.

Skipped unless ``$PYPLUGIN_GO_HOST_BIN`` points at the built host binary.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
GO_HOST = os.environ.get("PYPLUGIN_GO_HOST_BIN") or "/tmp/goplugin-interop/go-host-bin"
PYTHON = sys.executable
PLUGIN = ROOT / "fixtures" / "example_kv" / "plugin_main_for_go_host.py"


def _run(env_extra: dict[str, str], key: str, value: str) -> str:
    env = dict(os.environ)
    env.update(env_extra)
    out = subprocess.check_output(
        [GO_HOST, PYTHON, str(PLUGIN), "putget", key, value],
        env=env, stderr=subprocess.STDOUT, timeout=30,
    )
    return out.decode()


@pytest.mark.skipif(not pathlib.Path(GO_HOST).exists(),
                    reason=f"go host binary not found at {GO_HOST}")
def test_go_host_drives_python_plugin_no_mtls():
    out = _run({}, "k1", "from-go-host-no-mtls")
    assert out == "from-go-host-no-mtls"


@pytest.mark.skipif(not pathlib.Path(GO_HOST).exists(),
                    reason=f"go host binary not found at {GO_HOST}")
def test_go_host_drives_python_plugin_with_p521_automtls():
    out = _run({"AUTO_MTLS": "1"}, "k2", "from-go-host-with-p521")
    assert out == "from-go-host-with-p521"
