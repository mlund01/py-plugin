# Greeter — minimal pyplugin example

A standalone, runnable example showing the smallest end-to-end shape of a
pyplugin host + plugin.

```
greeter/
├── proto/greeter.proto      # service definition (Greet, Count)
├── generated/               # checked-in grpclib stubs
├── shared.py                # HandshakeConfig + Plugin glue (used by both sides)
├── plugin.py                # plugin process entry point
├── host.py                  # host that launches plugin.py and calls it
└── README.md                # this file
```

## Run it

From the repo root:

```bash
# install pyplugin in dev mode if you haven't
.venv/bin/pip install -e '.[dev]'

# launch the host — it spawns the plugin subprocess and makes two RPCs
.venv/bin/python examples/greeter/host.py "ada"
```

Expected output:

```
launching plugin (auto_mtls=False)...
  Greet: 'hello, ada!'
  Count('the quick brown fox jumps over the lazy dog'): letters=35, words=9
```

## With AutoMTLS (ECDSA P-521)

```bash
AUTO_MTLS=1 .venv/bin/python examples/greeter/host.py "ada"
```

The host generates an ephemeral P-521 cert, hands its public key to the plugin
via `PLUGIN_CLIENT_CERT`, the plugin returns its own P-521 cert in handshake
field 6 (raw-DER, base64-RawStdEncoding'd), and the gRPC channel runs over
mTLS — exactly matching go-plugin's wire format.

## Regenerating the stubs

If you change `proto/greeter.proto`, regenerate:

```bash
.venv/bin/python -m grpc_tools.protoc -Iexamples/greeter/proto \
    --python_out=examples/greeter/generated \
    --grpclib_python_out=examples/greeter/generated \
    --plugin=protoc-gen-grpclib_python=$(pwd)/.venv/bin/protoc-gen-grpclib_python \
    examples/greeter/proto/greeter.proto

# Fix the generated absolute import to a relative one
sed -i.bak 's/^import \(greeter_pb2\)/from . import \1/' \
    examples/greeter/generated/greeter_grpc.py
rm examples/greeter/generated/*.bak
```

## What this example shows

1. **The Plugin glue pattern** — `GreeterPlugin` lives in `shared.py` and is
   imported by both `host.py` and `plugin.py`. Its `servicers()` method
   returns the grpclib servicer instances on the plugin side; its `stub()`
   method builds a typed client on the host side. This mirrors go-plugin's
   `GRPCPlugin` interface.
2. **HandshakeConfig** — both sides agree on the magic cookie key + value
   and a protocol version. If the user accidentally runs `plugin.py`
   directly, they get the friendly "this is a plugin, not a CLI" message
   and exit code 1.
3. **Async API** — servicers are `async def`, the host uses
   `async with Client(...)` and awaits stub methods. This is required
   because pyplugin runs on grpclib (pure-Python on top of `ssl`/OpenSSL,
   which supports the P-521 cert format that go-plugin uses).
4. **AutoMTLS toggle** — flipping `auto_mtls=True` is the only difference
   between insecure and full ECDSA-P-521 mTLS. Wire-compatible with a Go
   host that sets `AutoMTLS: true`.
