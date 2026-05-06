from __future__ import annotations

import pytest

from pyplugin.cookie import validate_or_exit
from pyplugin.handshake import HandshakeConfig

CFG = HandshakeConfig(protocol_version=1, magic_cookie_key="MY_COOKIE", magic_cookie_value="secret")


def test_match_returns_silently():
    validate_or_exit(CFG, env={"MY_COOKIE": "secret"})


def test_missing_exits(capsys):
    with pytest.raises(SystemExit) as exc:
        validate_or_exit(CFG, env={})
    assert exc.value.code == 1
    out = capsys.readouterr().err
    assert "This binary is a plugin" in out


def test_wrong_value_exits(capsys):
    with pytest.raises(SystemExit) as exc:
        validate_or_exit(CFG, env={"MY_COOKIE": "wrong"})
    assert exc.value.code == 1
    assert "This binary is a plugin" in capsys.readouterr().err


def test_misconfigured_exits(capsys):
    with pytest.raises(SystemExit) as exc:
        validate_or_exit(HandshakeConfig(1, "", ""), env={})
    assert exc.value.code == 1
    assert "Misconfigured" in capsys.readouterr().err
