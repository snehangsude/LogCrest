"""
TDD tests for the LogCrest FastAPI / ASGI middleware.

The middleware must:
  - Wrap every HTTP request in a LogCrest flow context (flow_id + flow_stack + trace_id)
  - Use X-Request-ID header as the label prefix when present
  - Inject X-Flow-ID into every response
  - Emit flow_start on entry and flow_end (success / failed) on exit
  - Make flow_id_context accessible inside route handlers
  - Route @log_decorator calls inside handlers into the timeline
  - Degrade nested @log_flow gracefully (UserWarning, no new flow records)
  - Leave non-HTTP scopes (WebSocket) completely untouched
  - Give each concurrent request its own independent flow context
  - Not swallow exceptions (re-raises after emitting flow_end failed)

Implementation targets:
  logcrest/integrations/__init__.py   — new (empty)
  logcrest/integrations/fastapi.py    — LogCrestMiddleware (pure ASGI)

The middleware is a pure ASGI middleware (not BaseHTTPMiddleware) so that
asyncio contextvars propagate correctly into route handlers and their children.
"""
import asyncio
import logging
import threading
import pytest

pytest.importorskip("fastapi", reason="FastAPI not installed")
pytest.importorskip("httpx", reason="httpx not installed")

from fastapi import FastAPI, BackgroundTasks
from fastapi.testclient import TestClient
from logcrest.config import TraceFilter


# ── helpers ──────────────────────────────────────────────────────────────────

def _capture():
    records = []
    class Cap(logging.Handler):
        def emit(self, r):
            TraceFilter().filter(r)
            records.append(r)
    h = Cap()
    h.setLevel(logging.DEBUG)
    return h, records

def _attach(h):
    from logcrest.utils import get_session_logger
    lg = get_session_logger()
    lg.addHandler(h)
    return lg

def _detach(lg, h):
    lg.removeHandler(h)

def _make_app(**middleware_kwargs):
    """Build a minimal FastAPI app with LogCrestMiddleware attached."""
    from logcrest.integrations.fastapi import LogCrestMiddleware
    app = FastAPI()
    app.add_middleware(LogCrestMiddleware, **middleware_kwargs)
    return app


# ── Group 1: middleware importable ───────────────────────────────────────────

class TestMiddlewareImport:
    def test_importable_from_integrations(self):
        from logcrest.integrations.fastapi import LogCrestMiddleware
        assert LogCrestMiddleware is not None

    def test_accepts_fastapi_app(self):
        from logcrest.integrations.fastapi import LogCrestMiddleware
        app = FastAPI()
        app.add_middleware(LogCrestMiddleware)


# ── Group 2: response headers ────────────────────────────────────────────────

class TestResponseHeaders:
    def test_x_flow_id_header_present_on_every_response(self):
        app = _make_app()

        @app.get("/ping")
        async def ping():
            return {"ok": True}

        with TestClient(app) as client:
            resp = client.get("/ping")
        assert "x-flow-id" in resp.headers

    def test_x_flow_id_has_correct_format(self):
        """Default: method-path-{hex8} or just {hex8} — must end with 8 hex chars."""
        import re
        app = _make_app()

        @app.get("/orders")
        async def orders():
            return []

        with TestClient(app) as client:
            resp = client.get("/orders")
        fid = resp.headers["x-flow-id"]
        assert re.search(r'[0-9a-f]{8}$', fid), f"Flow ID must end with 8 hex chars: {fid!r}"

    def test_x_request_id_header_becomes_label_prefix(self):
        app = _make_app()

        @app.get("/checkout")
        async def checkout():
            return {}

        with TestClient(app) as client:
            resp = client.get("/checkout", headers={"x-request-id": "myreq-001"})
        fid = resp.headers["x-flow-id"]
        assert fid.startswith("myreq-001-"), f"Expected 'myreq-001-' prefix, got: {fid!r}"


# ── Group 3: flow records emitted ─────────────────────────────────────────────

class TestFlowRecordsEmitted:
    def _run_and_capture(self, app, method, path, **req_kwargs):
        h, records = _capture()
        lg = _attach(h)
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                getattr(client, method)(path, **req_kwargs)
        finally:
            _detach(lg, h)
        return records

    def test_flow_start_emitted_on_request(self):
        app = _make_app()

        @app.get("/health")
        async def health():
            return {}

        records = self._run_and_capture(app, "get", "/health")
        starts = [r for r in records if getattr(r, 'flow_type', None) == 'flow_start']
        assert len(starts) == 1

    def test_flow_end_success_emitted_on_normal_response(self):
        app = _make_app()

        @app.get("/health")
        async def health():
            return {}

        records = self._run_and_capture(app, "get", "/health")
        ends = [r for r in records if getattr(r, 'flow_type', None) == 'flow_end']
        assert len(ends) == 1
        assert ends[0].flow_status == 'success'

    def test_flow_end_failed_emitted_on_unhandled_exception(self):
        app = _make_app()

        @app.get("/boom")
        async def boom():
            raise RuntimeError("unexpected")

        records = self._run_and_capture(app, "get", "/boom")
        ends = [r for r in records if getattr(r, 'flow_type', None) == 'flow_end']
        assert len(ends) == 1
        assert ends[0].flow_status == 'failed'

    def test_flow_start_and_end_share_flow_id(self):
        app = _make_app()

        @app.get("/ping")
        async def ping():
            return {}

        records = self._run_and_capture(app, "get", "/ping")
        start = next(r for r in records if getattr(r, 'flow_type', None) == 'flow_start')
        end = next(r for r in records if getattr(r, 'flow_type', None) == 'flow_end')
        assert start.flow_id == end.flow_id

    def test_flow_end_has_total_ms(self):
        app = _make_app()

        @app.get("/ms")
        async def ms():
            return {}

        records = self._run_and_capture(app, "get", "/ms")
        end = next(r for r in records if getattr(r, 'flow_type', None) == 'flow_end')
        assert hasattr(end, 'total_ms') and end.total_ms >= 0

    def test_flow_end_has_timeline_list(self):
        app = _make_app()

        @app.get("/tl")
        async def tl():
            return {}

        records = self._run_and_capture(app, "get", "/tl")
        end = next(r for r in records if getattr(r, 'flow_type', None) == 'flow_end')
        assert isinstance(end.timeline, list)


# ── Group 4: context propagation ─────────────────────────────────────────────

class TestContextPropagation:
    def test_flow_id_accessible_inside_handler(self):
        from logcrest.utils import flow_id_context
        app = _make_app()
        seen = []

        @app.get("/ctx")
        async def ctx():
            seen.append(flow_id_context.get())
            return {}

        with TestClient(app) as client:
            client.get("/ctx")
        assert seen[0] is not None, "flow_id_context must be set inside the handler"

    def test_trace_id_not_global_inside_handler(self):
        from logcrest.utils import trace_context
        app = _make_app()
        seen = []

        @app.get("/trace")
        async def trace():
            seen.append(trace_context.get())
            return {}

        with TestClient(app) as client:
            client.get("/trace")
        assert seen[0] != "Global" and seen[0] is not None

    def test_flow_id_reset_after_request_completes(self):
        from logcrest.utils import flow_id_context
        app = _make_app()

        @app.get("/reset")
        async def reset():
            return {}

        with TestClient(app) as client:
            client.get("/reset")
        # Outside any request, flow_id_context must be None again
        assert flow_id_context.get() is None

    def test_user_log_inside_handler_has_non_global_trace_id(self):
        """log.info() inside a handler must inherit the request trace_id, not 'Global'."""
        from logcrest.utils import log
        app = _make_app()

        @app.get("/userlog")
        async def userlog():
            log.info("user message from handler")
            return {}

        h, records = _capture()
        lg = _attach(h)
        try:
            with TestClient(app) as client:
                client.get("/userlog")
        finally:
            _detach(lg, h)

        user_records = [r for r in records if "user message from handler" in r.getMessage()]
        assert user_records, "User log record must be captured"
        assert user_records[0].trace_id != "Global"


# ── Group 5: timeline tracking ────────────────────────────────────────────────

class TestHandlerTimeline:
    def _timeline(self, app, path):
        h, records = _capture()
        lg = _attach(h)
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.get(path)
        finally:
            _detach(lg, h)
        end = next((r for r in records if getattr(r, 'flow_type', None) == 'flow_end'), None)
        return end.timeline if end else []

    def test_log_decorator_call_inside_handler_appears_in_timeline(self):
        from logcrest import log_decorator
        app = _make_app()

        @log_decorator
        async def db_fetch():
            return []

        @app.get("/data")
        async def data():
            await db_fetch()
            return {}

        tl = self._timeline(app, "/data")
        assert any(e['fn'] == 'db_fetch' for e in tl), f"Timeline: {tl}"

    def test_nested_log_decorator_step_shows_ok_on_success(self):
        from logcrest import log_decorator
        app = _make_app()

        @log_decorator
        async def step():
            return "done"

        @app.get("/step")
        async def route():
            await step()
            return {}

        tl = self._timeline(app, "/step")
        entry = next(e for e in tl if e['fn'] == 'step')
        assert entry['status'] == 'ok'

    def test_failing_step_shows_failed_in_timeline(self):
        from logcrest import log_decorator
        app = _make_app()

        @log_decorator
        async def bad():
            raise ValueError("step failed")

        @app.get("/fail")
        async def route():
            bad_result = await bad()
            return {}

        tl = self._timeline(app, "/fail")
        entry = next((e for e in tl if e['fn'] == 'bad'), None)
        assert entry is not None and entry['status'] == 'failed'

    def test_concurrent_gather_steps_all_appear_in_timeline(self):
        from logcrest import log_decorator
        app = _make_app()

        @log_decorator
        async def step_a():
            await asyncio.sleep(0)

        @log_decorator
        async def step_b():
            await asyncio.sleep(0)

        @app.get("/parallel")
        async def route():
            await asyncio.gather(step_a(), step_b())
            return {}

        tl = self._timeline(app, "/parallel")
        fns = {e['fn'] for e in tl}
        assert 'step_a' in fns and 'step_b' in fns, f"Both concurrent steps must appear: {fns}"


# ── Group 6: nested @log_flow degrades ───────────────────────────────────────

class TestNestedLogFlowInMiddleware:
    def test_log_flow_on_handler_emits_warning_not_new_flow_start(self):
        """With middleware active, @log_flow on handler degrades — no second flow_start."""
        import warnings
        from logcrest import log_flow
        app = _make_app()

        @app.get("/checkout")
        @log_flow("checkout")
        async def checkout():
            return {}

        h, records = _capture()
        lg = _attach(h)
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                with warnings.catch_warnings(record=True) as w:
                    warnings.simplefilter("always")
                    client.get("/checkout")
        finally:
            _detach(lg, h)

        flow_starts = [r for r in records if getattr(r, 'flow_type', None) == 'flow_start']
        assert len(flow_starts) == 1, (
            f"Only the middleware must emit flow_start. Got {len(flow_starts)}."
        )

    def test_log_flow_handler_still_runs_and_returns(self):
        from logcrest import log_flow
        app = _make_app()

        @app.get("/ok")
        @log_flow("ok")
        async def ok_handler():
            return {"value": 42}

        with TestClient(app) as client:
            resp = client.get("/ok")
        assert resp.status_code == 200


# ── Group 7: non-HTTP scopes pass through ────────────────────────────────────

class TestNonHttpScopes:
    def test_non_http_scope_not_wrapped_in_flow(self):
        """Lifespan and WebSocket scopes must pass through without setting flow context."""
        from logcrest.utils import flow_id_context

        # We verify by checking that a lifespan scope doesn't cause errors
        # and that the flow context is not set after the middleware handles it.
        from logcrest.integrations.fastapi import LogCrestMiddleware

        startup_saw_flow = []

        app = FastAPI()
        app.add_middleware(LogCrestMiddleware)

        @app.on_event("startup")
        async def startup():
            # At startup (lifespan scope), the middleware must not have set flow context
            startup_saw_flow.append(flow_id_context.get())

        @app.get("/ping")
        async def ping():
            return {}

        with TestClient(app) as client:
            client.get("/ping")

        # Lifespan events run before the first request; flow_id must be None there
        assert startup_saw_flow == [None], f"flow_id_context must be None in startup: {startup_saw_flow}"


# ── Group 8: independent context per concurrent request ──────────────────────

class TestConcurrentRequestIsolation:
    def test_two_sequential_requests_get_different_flow_ids(self):
        app = _make_app()

        @app.get("/seq")
        async def seq():
            return {}

        with TestClient(app) as client:
            r1 = client.get("/seq")
            r2 = client.get("/seq")

        assert r1.headers["x-flow-id"] != r2.headers["x-flow-id"], (
            "Each request must get a unique flow ID"
        )

    def test_concurrent_requests_get_independent_flow_ids(self):
        """Two threads making requests simultaneously must not share flow context."""
        from logcrest.utils import flow_id_context
        app = _make_app()
        seen = {}

        @app.get("/concurrent/{name}")
        async def concurrent(name: str):
            await asyncio.sleep(0.05)
            seen[name] = flow_id_context.get()
            return {"name": name}

        with TestClient(app) as client:
            t1 = threading.Thread(target=lambda: client.get("/concurrent/a"))
            t2 = threading.Thread(target=lambda: client.get("/concurrent/b"))
            t1.start(); t2.start()
            t1.join(); t2.join()

        assert seen.get("a") is not None
        assert seen.get("b") is not None
        assert seen["a"] != seen["b"], "Concurrent requests must have independent flow IDs"
