"""AutoMTLS — ephemeral certificate generation matching go-plugin/mtls.go EXACTLY.

go-plugin uses ECDSA P-521 + SHA-512. Python's ``ssl`` module (OpenSSL,
which grpclib runs on) supports this natively, so we can match
go-plugin's cert template byte-for-byte:

* Curve: ECDSA P-521 (SECP521R1)
* Signature: ECDSA-SHA-512
* CN/SAN: ``localhost``
* O: ``HashiCorp``
* IsCA: true, BasicConstraints critical
* KeyUsage: digital signature | key encipherment | key agreement | cert sign
* ExtKeyUsage: clientAuth + serverAuth
* Validity: NotBefore -30s, NotAfter +262980h (~30 years)

The host's leaf cert is sent to the plugin via ``PLUGIN_CLIENT_CERT`` (PEM);
the plugin's leaf is returned as base64.RawStdEncoding(DER) in handshake
field 6.

Both sides pin the peer's leaf cert as the trust root and use
``RequireAndVerifyClientCert`` semantics.
"""
from __future__ import annotations

import base64
import datetime
import secrets
import ssl
from dataclasses import dataclass

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

_NOT_BEFORE_SKEW = datetime.timedelta(seconds=30)
_VALIDITY = datetime.timedelta(hours=262980)
_HOST = "localhost"


@dataclass(frozen=True)
class Cert:
    """A self-signed leaf usable as both the cert and its own CA (matches go-plugin)."""
    cert_pem: bytes
    key_pem: bytes
    cert_der: bytes


def generate() -> Cert:
    """Generate one ephemeral cert+key pair, byte-compatible with go-plugin's ``generateCert``."""
    key = ec.generate_private_key(ec.SECP521R1())

    # Match Go's serial: random in [0, 2^128).
    serial = int.from_bytes(secrets.token_bytes(16), "big")

    now = datetime.datetime.now(datetime.timezone.utc)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, _HOST),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "HashiCorp"),
    ])

    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(serial)
        .not_valid_before(now - _NOT_BEFORE_SKEW)
        .not_valid_after(now + _VALIDITY)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(_HOST)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=True,
                key_cert_sign=True,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([
                x509.ExtendedKeyUsageOID.CLIENT_AUTH,
                x509.ExtendedKeyUsageOID.SERVER_AUTH,
            ]),
            critical=False,
        )
    )

    cert = builder.sign(private_key=key, algorithm=hashes.SHA512())
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,  # "EC PRIVATE KEY"
        encryption_algorithm=serialization.NoEncryption(),
    )
    return Cert(cert_pem=cert_pem, key_pem=key_pem, cert_der=cert_der)


def encode_handshake_cert(cert_der: bytes) -> str:
    """Encode a leaf cert DER for handshake field 6: base64.RawStdEncoding (no padding)."""
    return base64.b64encode(cert_der).rstrip(b"=").decode("ascii")


def decode_handshake_cert(b64: str) -> bytes:
    """Inverse of :func:`encode_handshake_cert` — returns raw DER bytes."""
    pad = "=" * (-len(b64) % 4)
    return base64.b64decode(b64 + pad)


def der_to_pem(cert_der: bytes) -> bytes:
    """Wrap a raw DER cert in a single PEM CERTIFICATE block."""
    cert = x509.load_der_x509_certificate(cert_der)
    return cert.public_bytes(serialization.Encoding.PEM)


def server_ssl_context(*, cert_pem: bytes, key_pem: bytes, peer_cert_pem: bytes) -> ssl.SSLContext:
    """Build a server-side ``SSLContext`` mirroring go-plugin's tls.Config:

    ``Certificates``, ``RequireAndVerifyClientCert``, ``ClientCAs=peer``,
    ``RootCAs=peer``, ``MinVersion=TLS1.2``, ``ServerName=localhost``.
    Uses ALPN ``h2`` for HTTP/2.
    """
    import tempfile
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.set_alpn_protocols(["h2"])
    # SSLContext.load_* take file paths only — write to temp files.
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as cf, \
         tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as kf, \
         tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as rf:
        cf.write(cert_pem); cf.flush()
        kf.write(key_pem); kf.flush()
        rf.write(peer_cert_pem); rf.flush()
        ctx.load_cert_chain(certfile=cf.name, keyfile=kf.name)
        ctx.load_verify_locations(cafile=rf.name)
    return ctx


def client_ssl_context(*, cert_pem: bytes, key_pem: bytes, peer_cert_pem: bytes) -> ssl.SSLContext:
    """Build a client-side ``SSLContext`` for AutoMTLS.

    Trust root is the peer's cert; we present our own cert+key as client cert.
    Hostname verification is **disabled** because (a) we're connecting over
    unix sockets where there's no real hostname, and (b) we've already pinned
    the exact peer cert, so hostname check would be redundant anyway.
    """
    import tempfile
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.set_alpn_protocols(["h2"])
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as cf, \
         tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as kf, \
         tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as rf:
        cf.write(cert_pem); cf.flush()
        kf.write(key_pem); kf.flush()
        rf.write(peer_cert_pem); rf.flush()
        ctx.load_cert_chain(certfile=cf.name, keyfile=kf.name)
        ctx.load_verify_locations(cafile=rf.name)
    return ctx
