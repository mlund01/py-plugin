# pyplugin

A Python port of [HashiCorp's go-plugin](https://github.com/hashicorp/go-plugin),
wire-compatible with the original. Subprocess-based plugins, gRPC transport,
stdout-handshake protocol, magic-cookie validation, AutoMTLS, graceful shutdown,
GRPCBroker for bidirectional sub-channels, and reattach.

## Quick start

### Plugin

```python
# my_plugin.py
from pyplugin import HandshakeConfig, Plugin, ServeConfig, serve
import grpc

# (your generated stubs)
import myservice_pb2_grpc, myservice_pb2

class MyServicer(myservice_pb2_grpc.MyServiceServicer):
    def Greet(self, request, context):
        return myservice_pb2.GreetResponse(message=f"hello {request.name}")

class MyPlugin(Plugin):
    def grpc_server(self, broker, server):
        myservice_pb2_grpc.add_MyServiceServicer_to_server(MyServicer(), server)
    def grpc_client(self, broker, channel):
        return myservice_pb2_grpc.MyServiceStub(channel)

if __name__ == "__main__":
    serve(ServeConfig(
        handshake_config=HandshakeConfig(
            protocol_version=1,
            magic_cookie_key="MYPLUGIN_COOKIE",
            magic_cookie_value="hello",
        ),
        plugins={"my": MyPlugin()},
    ))
```

### Host

```python
import sys
from pyplugin import Client, ClientConfig, HandshakeConfig

with Client(ClientConfig(
    handshake_config=HandshakeConfig(1, "MYPLUGIN_COOKIE", "hello"),
    plugins={"my": MyPlugin()},
    cmd=[sys.executable, "my_plugin.py"],
    auto_mtls=True,
)) as client:
    stub = client.dispense("my")
    print(stub.Greet(myservice_pb2.GreetRequest(name="world")).message)
```

## What's implemented

| Feature | Status |
| --- | --- |
| stdout handshake protocol (6/7 segments) | ✅ |
| magic cookie validation | ✅ |
| gRPC transport: unix sockets (POSIX) and TCP loopback | ✅ |
| AutoMTLS with ephemeral ECDSA certs | ✅ (P-256, see caveat) |
| `GRPCController.Shutdown` graceful exit | ✅ |
| Kill ladder: Shutdown → SIGTERM → SIGKILL | ✅ |
| stderr forwarding with hclog parser (JSON + pretty) | ✅ |
| `GRPCBroker` bidirectional sub-channels (Accept/Dial) | ✅ |
| `GRPCStdio` post-handshake stdout/stderr stream | ✅ |
| `ReattachConfig` (host re-connects to running plugin) | ✅ |
| `VersionedPlugins` negotiation | ✅ |
| gRPC reflection + health (service name `plugin`) | ✅ |
| `PLUGIN_MULTIPLEX_GRPC` (broker over single socket) | ❌ deferred |

## Wire compatibility with go-plugin

pyplugin reuses go-plugin's `.proto` files verbatim (vendored from
`hashicorp/go-plugin/internal/plugin/`) with the same `package = "plugin"`
declaration, so all wire types are identical. The handshake line format,
magic-cookie env var, `PLUGIN_PROTOCOL_VERSIONS`, and `PLUGIN_CLIENT_CERT`
all match.

### AutoMTLS interop caveat

go-plugin generates **ECDSA P-521** ephemeral certs. pyplugin uses **ECDSA
P-256** because grpcio is built on BoringSSL, which rejects P-521 in TLS
handshakes (`NO_COMMON_SIGNATURE_ALGORITHMS`). Consequences:

- **Python ↔ Python**: works.
- **Python host ↔ Go plugin** with AutoMTLS: ❌ — the Go plugin generates
  a P-521 server cert that grpcio refuses to verify. Disable AutoMTLS for
  this combination, or patch go-plugin's `mtls.go` to use P-256.
- **Go host ↔ Python plugin** with AutoMTLS: ❌ — same reason, the Go host
  sends a P-521 client cert that the Python plugin's grpcio can't accept.
- Without AutoMTLS, all four directions interoperate over insecure unix
  sockets / TCP loopback.

## Layout

```
src/pyplugin/
  handshake.py      # protocol line format/parse
  cookie.py         # magic-cookie validation
  mtls.py           # ephemeral cert generation
  transport.py      # unix / tcp listener helpers
  server.py         # serve(ServeConfig) plugin entry point
  client.py         # Client / ClientConfig host launcher
  process.py        # cross-platform subprocess termination
  reattach.py       # ReattachConfig
  controller.py     # GRPCController.Shutdown servicer
  broker.py         # GRPCBroker bidirectional multiplexer
  stdio.py          # GRPCStdio post-handshake stream
  plugin.py         # Plugin ABC, PluginSet, VersionedPlugins
  logging_bridge.py # hclog (JSON + pretty) line parser
  errors.py         # exception hierarchy
  proto/            # vendored .proto files
  _generated/       # checked-in protoc stubs
fixtures/example_kv/  # example KV plugin used by smoke tests
tests/                # 40 tests covering all features above
```

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python scripts/gen_protos.py     # regenerate stubs
.venv/bin/python -m pytest                  # run tests
```

## License

MIT. The vendored `.proto` files in `src/pyplugin/proto/` and
`fixtures/example_kv/proto/` retain their upstream MPL-2.0 headers from
[hashicorp/go-plugin](https://github.com/hashicorp/go-plugin); MPL-2.0 is
file-level and compatible with MIT for the rest of the project.
