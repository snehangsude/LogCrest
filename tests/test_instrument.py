"""
TDD tests for logcrest.instrument(app) — one-liner FastAPI middleware setup.

Goal: instrument(app) attaches LogCrestMiddleware without requiring the user
to import or name any middleware class. Returns app for optional chaining.

Implementation targets:
  logcrest/__init__.py — expose instrument()
"""
import logging
import pytest

pytest.importorskip("fastapi", reason="FastAPI not installed")
pytest.importorskip("httpx", reason="httpx not installed")

from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── Group 1: API surface ──────────────────────────────────────────────────────

class TestInstrumentImport:
    def test_instrument_importable_from_logcrest(self):
        from logcrest import instrument
        assert callable(instrument)

    def test_middleware_importable_from_asgi_alias(self):
        from logcrest.integrations.asgi import LogCrestMiddleware
        assert LogCrestMiddleware is not None

    def test_asgi_alias_is_same_class_as_fastapi_path(self):
        from logcrest.integrations.asgi import LogCrestMiddleware as A
        from logcrest.integrations.fastapi import LogCrestMiddleware as F
        assert A is F

    def test_middleware_imports_no_starlette(self):
        """LogCrestMiddleware must not pull in starlette/fastapi at import time.

        Run in a clean subprocess: this test module imports fastapi at the top,
        which would otherwise pre-load starlette into sys.modules.
        """
        import subprocess
        import sys
        code = (
            "import sys; "
            "from logcrest.integrations.fastapi import LogCrestMiddleware; "
            "bad = [m for m in sys.modules if m == 'starlette' or m.startswith('starlette.') "
            "or m == 'fastapi' or m.startswith('fastapi.')]; "
            "assert not bad, bad; print('OK')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"Importing LogCrestMiddleware pulled in third-party modules.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_instrument_returns_the_app(self):
        from logcrest import instrument
        app = FastAPI()
        result = instrument(app)
        assert result is app

    def test_instrument_accepts_fastapi_app(self):
        from logcrest import instrument
        app = FastAPI()
        instrument(app)  # must not raise


# ── Group 2: middleware behaviour ────────────────────────────────────────────

class TestInstrumentMiddleware:
    def test_instrument_injects_x_flow_id_header(self):
        from logcrest import instrument
        app = FastAPI()

        @app.get("/ping")
        async def ping():
            return {}

        instrument(app)
        with TestClient(app) as client:
            resp = client.get("/ping")
        assert "x-flow-id" in resp.headers

    def test_instrument_flow_id_has_hex_suffix(self):
        import re
        from logcrest import instrument
        app = FastAPI()

        @app.get("/check")
        async def check():
            return {}

        instrument(app)
        with TestClient(app) as client:
            resp = client.get("/check")
        fid = resp.headers["x-flow-id"]
        assert re.search(r'[0-9a-f]{8}$', fid)

    def test_instrument_emits_flow_start_record(self):
        from logcrest import instrument
        from logcrest.utils import get_session_logger
        from logcrest.config import TraceFilter

        app = FastAPI()

        @app.get("/flow-check")
        async def flow_check():
            return {}

        instrument(app)
        records = []

        class Cap(logging.Handler):
            def emit(self, r):
                TraceFilter().filter(r)
                records.append(r)

        h = Cap()
        h.setLevel(logging.DEBUG)
        lg = get_session_logger()
        lg.addHandler(h)
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.get("/flow-check")
        finally:
            lg.removeHandler(h)

        starts = [r for r in records if getattr(r, 'flow_type', None) == 'flow_start']
        assert len(starts) == 1

    def test_instrument_emits_flow_end_record(self):
        from logcrest import instrument
        from logcrest.utils import get_session_logger
        from logcrest.config import TraceFilter

        app = FastAPI()

        @app.get("/end-check")
        async def end_check():
            return {}

        instrument(app)
        records = []

        class Cap(logging.Handler):
            def emit(self, r):
                TraceFilter().filter(r)
                records.append(r)

        h = Cap()
        h.setLevel(logging.DEBUG)
        lg = get_session_logger()
        lg.addHandler(h)
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.get("/end-check")
        finally:
            lg.removeHandler(h)

        ends = [r for r in records if getattr(r, 'flow_type', None) == 'flow_end']
        assert len(ends) == 1

    def test_instrument_accepts_level_kwarg(self):
        """instrument(app, level=...) must forward level to the middleware."""
        from logcrest import instrument
        app = FastAPI()

        @app.get("/lvl")
        async def lvl():
            return {}

        # Should not raise
        instrument(app, level=logging.DEBUG)
        with TestClient(app) as client:
            resp = client.get("/lvl")
        assert "x-flow-id" in resp.headers

    def test_two_instrument_calls_on_different_apps_are_independent(self):
        """Each instrumented app must have independent flow IDs."""
        from logcrest import instrument
        app_a = FastAPI()
        app_b = FastAPI()

        @app_a.get("/a")
        async def route_a():
            return {}

        @app_b.get("/b")
        async def route_b():
            return {}

        instrument(app_a)
        instrument(app_b)

        with TestClient(app_a) as ca, TestClient(app_b) as cb:
            ra = ca.get("/a")
            rb = cb.get("/b")

        assert ra.headers["x-flow-id"] != rb.headers["x-flow-id"]
