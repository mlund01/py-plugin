#!/usr/bin/env python3
"""Generate Python protobuf + grpclib stubs from vendored .proto files.

We use ``grpc_tools.protoc`` for the ``*_pb2.py`` (message types) and
grpclib's protoc plugin (``protoc-gen-grpclib_python``) for the
``*_grpc.py`` files (service stubs/bases).
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROTO_DIR = ROOT / "src" / "pyplugin" / "proto"
OUT_DIR = ROOT / "src" / "pyplugin" / "_generated"
EXAMPLE_PROTO_DIR = ROOT / "fixtures" / "example_kv" / "proto"
EXAMPLE_OUT_DIR = ROOT / "fixtures" / "example_kv" / "generated"


def run(out: pathlib.Path, proto_dir: pathlib.Path, files: list[str]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    plugin_path = shutil.which("protoc-gen-grpclib_python") or str(
        ROOT / ".venv" / "bin" / "protoc-gen-grpclib_python"
    )
    cmd = [
        sys.executable, "-m", "grpc_tools.protoc",
        f"-I{proto_dir}",
        f"--python_out={out}",
        f"--grpclib_python_out={out}",
        f"--plugin=protoc-gen-grpclib_python={plugin_path}",
        *files,
    ]
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True)
    rewrite_imports(out)


def rewrite_imports(out: pathlib.Path) -> None:
    """Rewrite generated absolute imports into relative ones."""
    pat = re.compile(r"^import (\w+_pb2)( as .+)?$", re.M)
    for py in list(out.glob("*_grpc.py")) + list(out.glob("*_pb2.py")):
        text = py.read_text()
        new = pat.sub(lambda m: f"from . import {m.group(1)}{m.group(2) or ''}", text)
        if new != text:
            py.write_text(new)


def main() -> None:
    run(OUT_DIR, PROTO_DIR, [
        str(PROTO_DIR / "grpc_broker.proto"),
        str(PROTO_DIR / "grpc_controller.proto"),
        str(PROTO_DIR / "grpc_stdio.proto"),
    ])
    (OUT_DIR / "__init__.py").write_text("")

    if EXAMPLE_PROTO_DIR.exists() and any(EXAMPLE_PROTO_DIR.glob("*.proto")):
        run(EXAMPLE_OUT_DIR, EXAMPLE_PROTO_DIR, [
            str(p) for p in EXAMPLE_PROTO_DIR.glob("*.proto")
        ])
        (EXAMPLE_OUT_DIR / "__init__.py").write_text("")


if __name__ == "__main__":
    main()
