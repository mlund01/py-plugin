"""Verify the AutoMTLS cert template matches what we promise."""
from __future__ import annotations

import datetime

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtensionOID

from pyplugin import mtls


def _load_pem(pem: bytes) -> x509.Certificate:
    return x509.load_pem_x509_certificate(pem)


def test_curve_is_p256():
    """We swap go-plugin's P-521 for P-256 because BoringSSL/grpcio rejects P-521."""
    cert = _load_pem(mtls.generate().cert_pem)
    pub = cert.public_key()
    assert isinstance(pub, ec.EllipticCurvePublicKey)
    assert pub.curve.name == "secp256r1"


def test_san_localhost():
    cert = _load_pem(mtls.generate().cert_pem)
    san = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
    assert "localhost" in [n.value for n in san]


def test_eku_client_and_server():
    cert = _load_pem(mtls.generate().cert_pem)
    eku = cert.extensions.get_extension_for_oid(ExtensionOID.EXTENDED_KEY_USAGE).value
    assert x509.ExtendedKeyUsageOID.CLIENT_AUTH in eku
    assert x509.ExtendedKeyUsageOID.SERVER_AUTH in eku


def test_basic_constraints_ca_true():
    cert = _load_pem(mtls.generate().cert_pem)
    bc = cert.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value
    assert bc.ca is True


def test_validity_about_30y():
    cert = _load_pem(mtls.generate().cert_pem)
    delta = cert.not_valid_after_utc - cert.not_valid_before_utc
    # 262980 hours = ~30 years.
    assert datetime.timedelta(days=29 * 365) < delta < datetime.timedelta(days=31 * 365)


def test_handshake_cert_round_trip():
    c = mtls.generate()
    b64 = mtls.encode_handshake_cert(c.cert_der)
    # No padding, std alphabet — go-plugin uses base64.RawStdEncoding.
    assert "=" not in b64
    assert mtls.decode_handshake_cert(b64) == c.cert_der
