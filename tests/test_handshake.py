from __future__ import annotations

import pytest

from pyplugin.errors import CoreProtocolMismatch, HandshakeError
from pyplugin.handshake import (
    CORE_PROTOCOL_VERSION,
    NETWORK_UNIX,
    PROTOCOL_GRPC,
    format_line,
    parse_line,
)


def test_format_basic_six_segments():
    line = format_line(
        app_protocol_version=2, network=NETWORK_UNIX, address="/tmp/sock", protocol=PROTOCOL_GRPC
    )
    assert line == "1|2|unix|/tmp/sock|grpc|"


def test_format_with_cert():
    line = format_line(
        app_protocol_version=3,
        network="tcp",
        address="127.0.0.1:1234",
        server_cert="MIIBcert" * 8,
    )
    assert line.startswith("1|3|tcp|127.0.0.1:1234|grpc|MIIBcert")
    assert line.count("|") == 5


def test_format_multiplex_appended():
    line = format_line(
        app_protocol_version=1,
        network=NETWORK_UNIX,
        address="/tmp/x",
        multiplex_supported=True,
    )
    assert line.endswith("|true")
    assert line.count("|") == 6


def test_parse_round_trip():
    raw = format_line(app_protocol_version=7, network="tcp", address="1.2.3.4:5", server_cert="")
    p = parse_line(raw)
    assert p.core_protocol_version == CORE_PROTOCOL_VERSION
    assert p.app_protocol_version == 7
    assert p.network == "tcp"
    assert p.address == "1.2.3.4:5"
    assert p.protocol == PROTOCOL_GRPC
    assert p.server_cert == ""
    assert p.multiplex_supported is False


def test_parse_with_cert_long():
    cert = "A" * 64
    raw = f"1|1|unix|/tmp/sock|grpc|{cert}"
    p = parse_line(raw)
    assert p.server_cert == cert


def test_parse_short_cert_treated_as_extra_legacy():
    # Mirrors go-plugin's `len > 50` sniff to ignore legacy "extra" data.
    raw = "1|1|unix|/tmp/sock|grpc|short"
    p = parse_line(raw)
    assert p.server_cert == ""


def test_parse_four_segments_defaults_to_netrpc():
    p = parse_line("1|1|unix|/tmp/sock")
    assert p.protocol == "netrpc"


def test_parse_rejects_bad_core_version():
    with pytest.raises(CoreProtocolMismatch):
        parse_line("2|1|unix|/tmp/sock|grpc|")


def test_parse_rejects_too_few_segments():
    with pytest.raises(HandshakeError):
        parse_line("1|1|unix")


def test_parse_strips_trailing_newline():
    p = parse_line("1|1|unix|/tmp/sock|grpc|\n")
    assert p.address == "/tmp/sock"


def test_parse_multiplex_true():
    p = parse_line("1|1|unix|/tmp/sock|grpc||true")
    assert p.multiplex_supported is True
