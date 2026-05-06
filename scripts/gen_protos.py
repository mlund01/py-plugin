#!/usr/bin/env python3
"""Generate Python gRPC stubs from vendored .proto files.

Run with: python scripts/gen_protos.py
"""
from __future__ import annotations

import pathlib
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
    cmd = [
        sys.executable, "-m", "grpc_tools.protoc",
        f"-I{proto_dir}",
        f"--python_out={out}",
        f"--grpc_python_out={out}",
        *files,
    ]
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True)
    rewrite_imports(out)


def rewrite_imports(out: pathlib.Path) -> None:
    """Rewrite generated absolute imports into relative ones so the dir works as a package."""
    import re
    pat = re.compile(r"^import (\w+_pb2)( as .+)?$", re.M)
    for py in out.glob("*_pb2_grpc.py"):
        text = py.read_text()
        text = pat.sub(lambda m: f"from . import {m.group(1)}{m.group(2) or ''}", text)
        py.write_text(text)
    for py in out.glob("*_pb2.py"):
        text = py.read_text()
        text = pat.sub(lambda m: f"from . import {m.group(1)}{m.group(2) or ''}", text)
        py.write_text(text)


def main() -> None:
    if shutil.which("python") is None:
        sys.exit("python not on PATH")

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
