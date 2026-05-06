"""AutoMTLS — ephemeral certificate generation matching go-plugin/mtls.go.

go-plugin uses ECDSA P-521 + SHA-512 because Go's stdlib TLS supports it
freely. grpcio is built on BoringSSL, which does *not* support P-521 in TLS
(``NO_COMMON_SIGNATURE_ALGORITHMS``) — so we use ECDSA P-256 + SHA-256 here.
Everything else matches: CN/SAN ``localhost``, IsCA=true, KeyUsage = digital
signature | key encipherment | key agreement | cert sign, ExtKeyUsage =
client + server auth, validity from ``-30s`` to ``+262980h`` (~30y). The
host's leaf cert is sent to the plugin via the ``PLUGIN_CLIENT_CERT`` env var
(PEM); the plugin's leaf is returned as base64.RawStdEncoding(DER) in
handshake field 6.

Both ends pin the peer's leaf cert as the CA; the server uses
``RequireAndVerifyClientCert`` and ``ServerName=localhost``.

Interop caveat: when AutoMTLS is enabled and the peer is a Go-plugin
process using stock go-plugin (P-521), TLS will fail. Either disable
AutoMTLS or patch go-plugin's mtls.go to use P-256.
"""
from __future__ import annotations

import base64
import datetime
import secrets
from dataclasses import dataclass

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

# Match go-plugin: 30-second skew back, ~30 years forward.
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
    """Generate one ephemeral cert+key pair (P-256 / SHA-256, see module docstring)."""
    key = ec.generate_private_key(ec.SECP256R1())

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

    cert = builder.sign(private_key=key, algorithm=hashes.SHA256())
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,  # "EC PRIVATE KEY"
        encryption_algorithm=serialization.NoEncryption(),
    )
    return Cert(cert_pem=cert_pem, key_pem=key_pem, cert_der=cert_der)


def encode_handshake_cert(cert_der: bytes) -> str:
    """Encode a leaf cert DER for handshake field 6: base64 std alphabet, no padding."""
    return base64.b64encode(cert_der).rstrip(b"=").decode("ascii")


def decode_handshake_cert(b64: str) -> bytes:
    """Inverse of ``encode_handshake_cert``: returns the cert DER bytes."""
    pad = "=" * (-len(b64) % 4)
    return base64.b64decode(b64 + pad)


def der_to_pem(cert_der: bytes) -> bytes:
    """Wrap a raw DER cert in a single PEM CERTIFICATE block."""
    cert = x509.load_der_x509_certificate(cert_der)
    return cert.public_bytes(serialization.Encoding.PEM)
