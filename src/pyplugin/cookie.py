"""Magic-cookie validation. UX feature, not a security boundary.

If the cookie doesn't match, we print the same human-friendly message
go-plugin uses (so users who run a plugin binary directly get a useful hint)
and exit 1.
"""
from __future__ import annotations

import os
import sys

from .handshake import HandshakeConfig

_NOT_A_CLI_MESSAGE = (
    "This binary is a plugin. These are not meant to be executed directly.\n"
    "Please execute the program that consumes these plugins, which will\n"
    "load any plugins automatically\n"
)

_MISCONFIG_MESSAGE = (
    "Misconfigured ServeConfig given to serve this plugin: no magic cookie\n"
    "key or value was set. Please notify the plugin author and report\n"
    "this as a bug.\n"
)


def validate_or_exit(config: HandshakeConfig, env: os._Environ[str] | None = None) -> None:
    """Verify the magic cookie env var matches; otherwise print a friendly
    message and ``sys.exit(1)``.

    This is the first thing a plugin's ``serve()`` does. Run it before
    importing heavy deps so the user-facing message stays clean.
    """
    if env is None:
        env = os.environ

    if not config.magic_cookie_key or not config.magic_cookie_value:
        sys.stderr.write(_MISCONFIG_MESSAGE)
        sys.exit(1)

    if env.get(config.magic_cookie_key) != config.magic_cookie_value:
        sys.stderr.write(_NOT_A_CLI_MESSAGE)
        sys.exit(1)
