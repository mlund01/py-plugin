"""Parse hclog log lines into structured ``logging.LogRecord`` calls.

go-plugin pipes plugin stderr through go-hclog. hclog has two output modes:

* JSON: ``{"@level":"info","@message":"...","@module":"foo","@timestamp":"...",...}``
* Pretty: ``2025-01-01T12:00:00.000Z [INFO]  module: msg: key=value key2="quoted"``

We try JSON first (cheap discriminator: starts with ``{``) and fall back to
the pretty regex. Anything we can't parse is logged at INFO with the raw
text. We always emit on the caller's logger so they can hook formatters.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

_LEVELS = {
    "trace": logging.DEBUG,  # logging has no TRACE; map to DEBUG
    "debug": logging.DEBUG,
    "info":  logging.INFO,
    "warn":  logging.WARNING,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "fatal": logging.CRITICAL,
    "critical": logging.CRITICAL,
}

# Pretty format: optional timestamp, then [LEVEL]  module: message ...
_PRETTY = re.compile(
    r"^(?P<ts>\S+)?\s*\[(?P<level>\w+)\]\s*(?P<module>[^:]+):\s*(?P<rest>.*)$"
)


def emit(logger: logging.Logger, raw: str) -> None:
    """Parse ``raw`` and emit on ``logger`` at the matching level."""
    raw = raw.rstrip("\r\n")
    if not raw:
        return

    if raw.lstrip().startswith("{"):
        rec = _parse_json(raw)
        if rec is not None:
            level, msg, module, extra = rec
            logger.log(level, msg, extra={"plugin": module, "fields": extra})
            return

    m = _PRETTY.match(raw)
    if m is not None:
        level = _LEVELS.get(m["level"].lower(), logging.INFO)
        module = m["module"].strip()
        logger.log(level, m["rest"].strip(), extra={"plugin": module})
        return

    logger.info(raw)


def _parse_json(raw: str) -> tuple[int, str, str, dict[str, Any]] | None:
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    level = _LEVELS.get(str(obj.pop("@level", "info")).lower(), logging.INFO)
    msg = str(obj.pop("@message", ""))
    module = str(obj.pop("@module", ""))
    obj.pop("@timestamp", None)
    return level, msg, module, obj
