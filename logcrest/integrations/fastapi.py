"""
LogCrest ASGI middleware (FastAPI / Starlette / Quart / any ASGI framework).

Wraps every HTTP request in a LogCrest flow context so that:
  - Every request gets a unique flow_id (label-{hex8} or {hex8}).
  - X-Request-ID header is used as the label prefix when present.
  - X-Flow-ID is injected into every response.
  - flow_start / flow_end records are emitted automatically.
  - @log_decorator calls inside route handlers appear in the request timeline.
  - flow_id_context and trace_context are available throughout the request,
    including inside background tasks and async callables.
  - Nested @log_flow on individual handlers degrades gracefully (UserWarning,
    function added to outer timeline — no duplicate flow_start/flow_end).

Usage:
    from fastapi import FastAPI
    import logcrest

    app = FastAPI()
    logcrest.instrument(app)            # one-liner

    # or, explicitly / for non-FastAPI ASGI apps:
    from logcrest.integrations.fastapi import LogCrestMiddleware
    app.add_middleware(LogCrestMiddleware)        # FastAPI / Starlette
    app = LogCrestMiddleware(app)                 # any raw ASGI app

Zero dependencies:
  This module is pure stdlib ASGI — it does NOT import Starlette, FastAPI, or
  any third-party package. It works with any ASGI server/framework and adds no
  weight to LogCrest's dependency footprint. (WSGI frameworks like Flask or
  classic Django-WSGI are not ASGI; use @log_flow / `with log_flow()` directly
  in those views instead.)

Implementation notes:
  - Pure ASGI (not BaseHTTPMiddleware) ensures contextvars propagate correctly
    to route handlers and their children without copying.
  - asyncio.gather / asyncio.create_task: tasks receive a context copy but
    share the mutable flow_stack list by reference, so concurrent steps all
    appear in the timeline.
"""
import time
import logging
from typing import Any, Awaitable, Callable, MutableMapping

# Pure-stdlib ASGI type aliases — no Starlette import required.
Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

from ..flow import _make_flow_id, _emit_start, _emit_end_success, _emit_end_failure
from ..utils import flow_id_context, flow_stack_context, trace_context


def _sanitize(value: str) -> str:
    """Neutralize CR/LF so an attacker-controlled path cannot forge log lines.

    Newlines are escaped (not stripped) so the content stays visible for
    debugging but can never span multiple log lines.
    """
    return value.replace("\r", "\\r").replace("\n", "\\n")


class LogCrestMiddleware:
    """Pure ASGI middleware that wraps every HTTP request in a LogCrest flow.

    Parameters
    ----------
    app:
        The downstream ASGI application.
    level:
        Log level for flow_start and flow_end (success) records.
        Failures always emit at ERROR regardless of this setting.
    """

    def __init__(self, app: ASGIApp, level: int = logging.INFO) -> None:
        self.app = app
        self.level = level

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "/")

        # Prefer X-Request-ID as label; fall back to method+path slug
        raw_headers = scope.get("headers", [])
        header_map = {k.lower(): v for k, v in raw_headers}
        req_id = header_map.get(b"x-request-id", b"").decode("utf-8", errors="ignore").strip()

        if req_id:
            label = req_id
        else:
            path_slug = path.replace("/", "-").strip("-") or "root"
            label = f"{method.lower()}-{path_slug}"

        flow_id = _make_flow_id(label)
        stack: list = []

        fid_tok = flow_id_context.set(flow_id)
        stk_tok = flow_stack_context.set(stack)
        trc_tok = trace_context.set(flow_id[:8])

        route_label = _sanitize(f"{method} {path}")
        _emit_start(route_label, flow_id, self.level, False, (), {})
        t0 = time.perf_counter()

        async def _send(message: Message) -> None:
            if message["type"] == "http.response.start":
                # Inject X-Flow-ID. ASGI headers is an iterable of (bytes, bytes);
                # copy to a list before appending so we never mutate a tuple/shared seq.
                headers = list(message.get("headers") or [])
                headers.append((b"x-flow-id", flow_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, _send)
            elapsed = (time.perf_counter() - t0) * 1000
            _emit_end_success(route_label, flow_id, self.level, elapsed, stack)
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            _emit_end_failure(route_label, flow_id, elapsed, stack, exc)
            raise
        finally:
            flow_id_context.reset(fid_tok)
            flow_stack_context.reset(stk_tok)
            trace_context.reset(trc_tok)
