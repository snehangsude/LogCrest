"""
Security / robustness hardening tests.

Covers:
  #1 JSONFormatter must not drop records when an `extra` value is non-JSON-serializable.
  #2 The ASGI middleware must neutralize CR/LF in the request path (log forging).
"""
import asyncio
import json
import logging
import pytest


# ── #1: JSONFormatter resilience to non-serializable extras ──────────────────

class TestJSONNonSerializable:
    def test_non_serializable_extra_is_coerced_not_dropped(self):
        from logcrest.formatters import JSONFormatter

        class Weird:
            def __repr__(self):
                return "<weird-object>"

        r = logging.LogRecord("n", logging.INFO, "", 0, "msg", (), None)
        r.obj = Weird()  # non-JSON-serializable user context

        out = JSONFormatter().format(r)          # must not raise
        data = json.loads(out)                   # must be valid JSON
        assert "obj" in data
        assert data["obj"] == "<weird-object>"   # coerced via default=str

    def test_serializable_extras_unaffected(self):
        from logcrest.formatters import JSONFormatter
        r = logging.LogRecord("n", logging.INFO, "", 0, "msg", (), None)
        r.flow_id = "checkout-abc12345"
        r.steps = 3
        out = JSONFormatter().format(r)
        data = json.loads(out)
        assert data["flow_id"] == "checkout-abc12345"
        assert data["steps"] == 3

    def test_set_value_coerced_to_string(self):
        """A set is not JSON-serializable; default=str must rescue it."""
        from logcrest.formatters import JSONFormatter
        r = logging.LogRecord("n", logging.INFO, "", 0, "msg", (), None)
        r.tags = {"a", "b"}
        out = JSONFormatter().format(r)   # must not raise
        json.loads(out)                   # must be valid JSON


# ── #2: log forging via CR/LF in request path ────────────────────────────────

def _capture():
    from logcrest.utils import get_session_logger
    from logcrest.config import TraceFilter
    records = []

    class Cap(logging.Handler):
        def emit(self, r):
            TraceFilter().filter(r)
            records.append(r)

    h = Cap()
    h.setLevel(logging.DEBUG)
    lg = get_session_logger()
    lg.addHandler(h)
    return lg, h, records


class TestLogForgingSanitization:
    def _drive(self, path):
        """Drive LogCrestMiddleware directly with a crafted ASGI scope."""
        from logcrest.integrations.asgi import LogCrestMiddleware

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        mw = LogCrestMiddleware(app)
        scope = {"type": "http", "method": "GET", "path": path, "headers": []}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(_message):
            pass

        lg, h, records = _capture()
        try:
            asyncio.run(mw(scope, receive, send))
        finally:
            lg.removeHandler(h)
        return records

    def test_crlf_in_path_does_not_produce_raw_newline_in_records(self):
        records = self._drive("/orders\r\nINJECTED forged log line")
        for r in records:
            assert "\n" not in r.getMessage(), "Raw newline from path must be neutralized"
            assert "\r" not in r.getMessage(), "Raw carriage return from path must be neutralized"

    def test_injected_text_still_present_but_inert(self):
        """Sanitization should neutralize the newline, not silently erase content."""
        records = self._drive("/orders\r\nINJECTED")
        start = next((r for r in records if getattr(r, "flow_type", None) == "flow_start"), None)
        assert start is not None
        # The text survives (escaped) so nothing is hidden — it just can't span lines.
        assert "INJECTED" in start.getMessage()

    def test_normal_path_unchanged(self):
        records = self._drive("/orders/42")
        start = next((r for r in records if getattr(r, "flow_type", None) == "flow_start"), None)
        assert start is not None
        assert "/orders/42" in start.getMessage()
