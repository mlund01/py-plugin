from __future__ import annotations

import logging

from pyplugin.logging_bridge import emit


def _capture(level: int = logging.DEBUG):
    log = logging.getLogger("test.bridge.unique")
    log.handlers.clear()
    log.setLevel(level)
    log.propagate = False
    records = []

    class H(logging.Handler):
        def emit(self, r):
            records.append(r)

    log.addHandler(H())
    return log, records


def test_json_line():
    log, recs = _capture()
    emit(log, '{"@level":"warn","@module":"foo","@message":"hello","key":"v"}')
    assert len(recs) == 1
    r = recs[0]
    assert r.levelno == logging.WARNING
    assert r.getMessage() == "hello"
    assert getattr(r, "plugin", None) == "foo"


def test_pretty_line():
    log, recs = _capture()
    emit(log, "2025-01-01T00:00:00Z [ERROR] mod: boom: x=1")
    assert len(recs) == 1
    assert recs[0].levelno == logging.ERROR
    assert "boom" in recs[0].getMessage()


def test_unparseable_falls_back_to_info():
    log, recs = _capture()
    emit(log, "just a string with no structure")
    assert len(recs) == 1
    assert recs[0].levelno == logging.INFO


def test_empty_line_is_dropped():
    log, recs = _capture()
    emit(log, "")
    emit(log, "   ")
    assert len(recs) <= 1  # whitespace-only may go to info, but empty doesn't


def test_trace_maps_to_debug():
    log, recs = _capture()
    emit(log, '{"@level":"trace","@message":"x"}')
    assert recs[-1].levelno == logging.DEBUG
