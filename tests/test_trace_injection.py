"""
TDD tests for trace_id injection into user log.*() calls.

Bug A (handler-level): TraceFilter sets trace_id="Global" on user log calls even when
those calls happen inside a @log_decorator context where trace_context IS set.
The filter never reads from trace_context — it only checks hasattr(record).
Fix target: logcrest/config.py :: TraceFilter.filter()

Bug B (queue-level): Even after fixing TraceFilter, the async QueueListener runs
handlers in a background thread. By then, the calling thread's contextvars context
is gone, so trace_context.get() returns None in the background thread.
Records reaching the queue need trace_id captured BEFORE enqueueing (calling thread).
Fix target: logcrest/config.py :: TraceSnapshotFilter (new class)
            logcrest/core.py   :: attach TraceSnapshotFilter to QueueHandler
"""
import logging
import asyncio
import pytest
from logcrest.config import TraceFilter
from logcrest.utils import trace_context


# ---------------------------------------------------------------------------
# Unit tests — TraceFilter in isolation
# ---------------------------------------------------------------------------

class TestTraceFilterInjection:
    def _make_record(self, **extra):
        r = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="msg", args=(), exc_info=None,
        )
        for k, v in extra.items():
            setattr(r, k, v)
        return r

    def test_reads_trace_id_from_contextvar_when_missing_from_record(self):
        """Core fix: TraceFilter must pull trace_id from contextvars."""
        token = trace_context.set("ctx-abc-1234")
        try:
            record = self._make_record()
            assert not hasattr(record, "trace_id")
            TraceFilter().filter(record)
            assert record.trace_id == "ctx-abc-1234"
        finally:
            trace_context.reset(token)

    def test_falls_back_to_global_when_contextvar_is_none(self):
        """Outside any traced context the trace_id should be 'Global'."""
        token = trace_context.set(None)
        try:
            record = self._make_record()
            TraceFilter().filter(record)
            assert record.trace_id == "Global"
        finally:
            trace_context.reset(token)

    def test_preserves_explicit_trace_id_already_on_record(self):
        """If the record already has a trace_id, the filter must not overwrite it."""
        token = trace_context.set("ctx-should-be-ignored")
        try:
            record = self._make_record(trace_id="explicit-trace")
            TraceFilter().filter(record)
            assert record.trace_id == "explicit-trace"
        finally:
            trace_context.reset(token)

    def test_contextvar_not_set_at_all_falls_back_to_global(self):
        """ContextVar default is None; filter should still produce 'Global'."""
        record = self._make_record()
        # Do NOT set the contextvar — rely on its default (None)
        TraceFilter().filter(record)
        assert record.trace_id == "Global"

    def test_func_name_overridden_when_actual_func_name_present(self):
        record = self._make_record(actual_func_name="real_fn", funcName="wrapper")
        token = trace_context.set(None)
        try:
            TraceFilter().filter(record)
            assert record.funcName == "real_fn"
        finally:
            trace_context.reset(token)

    def test_func_name_untouched_when_actual_func_name_absent(self):
        record = self._make_record(funcName="my_func")
        token = trace_context.set(None)
        try:
            TraceFilter().filter(record)
            assert record.funcName == "my_func"
        finally:
            trace_context.reset(token)

    def test_filter_is_idempotent_across_multiple_handlers(self):
        """Simulates same record passing through multiple handlers each with TraceFilter."""
        token = trace_context.set("ctx-idem")
        try:
            record = self._make_record(actual_func_name="fn", funcName="wrapper")
            TraceFilter().filter(record)
            TraceFilter().filter(record)  # second handler
            assert record.trace_id == "ctx-idem"
            assert record.funcName == "fn"
        finally:
            trace_context.reset(token)


# ---------------------------------------------------------------------------
# Integration tests — decorator + user log.*(). Requires TraceFilter fix.
# ---------------------------------------------------------------------------

class TestUserLogInDecoratedContext:
    """
    These tests verify end-to-end: that a user calling log.info() inside
    a @log_decorator function gets the same trace_id as the decorator's own
    entry/exit messages — not "Global".

    Strategy: attach a synchronous capturing handler directly to the session
    logger (bypassing the async queue) so records are visible immediately.
    """

    def _attach_capturing_handler(self):
        from logcrest.utils import get_session_logger
        captured = []

        class SyncCapture(logging.Handler):
            def emit(self, record):
                # Run TraceFilter as handlers do
                TraceFilter().filter(record)
                captured.append(record)

        handler = SyncCapture()
        handler.setLevel(logging.DEBUG)
        logger = get_session_logger()
        logger.addHandler(handler)
        return logger, handler, captured

    def _detach(self, logger, handler):
        logger.removeHandler(handler)

    def test_user_log_inside_sync_decorated_fn_shares_trace_id(self):
        from logcrest import log_decorator
        from logcrest.utils import log

        logger, handler, captured = self._attach_capturing_handler()
        try:
            @log_decorator
            def work():
                log.info("user message inside")

            work()

            trace_ids = {r.trace_id for r in captured}
            assert "Global" not in trace_ids, (
                "log.info() inside @log_decorator must not produce trace_id='Global'"
            )
            assert len(trace_ids) == 1, "All messages in one call should share a trace_id"
        finally:
            self._detach(logger, handler)

    def test_user_log_outside_decorated_fn_gets_global(self):
        from logcrest.utils import log

        logger, handler, captured = self._attach_capturing_handler()
        try:
            log.info("message outside any decorated function")

            assert len(captured) >= 1
            assert captured[-1].trace_id == "Global"
        finally:
            self._detach(logger, handler)

    def test_user_log_inside_async_decorated_fn_shares_trace_id(self):
        from logcrest import log_decorator
        from logcrest.utils import log

        logger, handler, captured = self._attach_capturing_handler()
        try:
            @log_decorator
            async def async_work():
                log.info("async user message")

            asyncio.run(async_work())

            trace_ids = {r.trace_id for r in captured}
            assert "Global" not in trace_ids
            assert len(trace_ids) == 1
        finally:
            self._detach(logger, handler)

    def test_nested_calls_all_share_same_trace_id_including_user_logs(self):
        from logcrest import log_decorator
        from logcrest.utils import log

        logger, handler, captured = self._attach_capturing_handler()
        try:
            @log_decorator
            def inner():
                log.info("inner user log")

            @log_decorator
            def outer():
                log.info("outer user log")
                inner()

            outer()

            trace_ids = {r.trace_id for r in captured}
            assert "Global" not in trace_ids
            assert len(trace_ids) == 1, "Root + nested + user logs must share one trace_id"
        finally:
            self._detach(logger, handler)

    def test_two_separate_root_calls_get_different_trace_ids(self):
        from logcrest import log_decorator
        from logcrest.utils import log

        logger, handler, captured = self._attach_capturing_handler()
        try:
            @log_decorator
            def task():
                log.info("task user log")

            task()
            count_after_first = len(captured)
            task()

            first_batch = {r.trace_id for r in captured[:count_after_first]}
            second_batch = {r.trace_id for r in captured[count_after_first:]}

            assert len(first_batch) == 1
            assert len(second_batch) == 1
            assert first_batch != second_batch, "Each root invocation should have a unique trace_id"
        finally:
            self._detach(logger, handler)


# ---------------------------------------------------------------------------
# Queue-path trace_id (Bug B) — TraceSnapshotFilter on QueueHandler
# ---------------------------------------------------------------------------

class TestTraceSnapshotFilter:
    """
    TraceSnapshotFilter must be attached to the QueueHandler so it runs in the
    calling thread and captures trace_id BEFORE the record enters the async queue.
    TraceFilter on downstream handlers runs in the background thread where
    trace_context is always None, so it cannot fix this on its own.
    """

    def test_trace_snapshot_filter_exists_in_config(self):
        """TraceSnapshotFilter must be importable from logcrest.config."""
        from logcrest.config import TraceSnapshotFilter
        assert TraceSnapshotFilter is not None

    def test_snapshot_filter_sets_trace_id_from_contextvar(self):
        from logcrest.config import TraceSnapshotFilter

        token = trace_context.set("snap-abc-9999")
        try:
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="", lineno=0,
                msg="msg", args=(), exc_info=None,
            )
            TraceSnapshotFilter().filter(record)
            assert record.trace_id == "snap-abc-9999"
        finally:
            trace_context.reset(token)

    def test_snapshot_filter_sets_global_when_no_context(self):
        from logcrest.config import TraceSnapshotFilter

        token = trace_context.set(None)
        try:
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="", lineno=0,
                msg="msg", args=(), exc_info=None,
            )
            TraceSnapshotFilter().filter(record)
            assert record.trace_id == "Global"
        finally:
            trace_context.reset(token)

    def test_snapshot_filter_does_not_overwrite_existing_trace_id(self):
        from logcrest.config import TraceSnapshotFilter

        token = trace_context.set("ctx-should-not-win")
        try:
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="", lineno=0,
                msg="msg", args=(), exc_info=None,
            )
            record.trace_id = "already-set"
            TraceSnapshotFilter().filter(record)
            assert record.trace_id == "already-set"
        finally:
            trace_context.reset(token)

    def test_queue_handler_has_trace_snapshot_filter_attached(self, tmp_path):
        """After build(), the QueueHandler must have TraceSnapshotFilter attached."""
        import json
        from logging.handlers import QueueHandler
        from logcrest.config import TraceSnapshotFilter
        from logcrest.core import AsyncLoggerBuilder

        cfg = tmp_path / "cfg.json"
        cfg.write_text(json.dumps({
            "log_name": "svc_snapshot_test",
            "base_log_dir": str(tmp_path / "logs"),
        }))
        b = AsyncLoggerBuilder(config_path=cfg)
        logger = b.build()

        queue_handlers = [h for h in logger.handlers if isinstance(h, QueueHandler)]
        assert len(queue_handlers) == 1

        snapshot_filters = [f for f in queue_handlers[0].filters if isinstance(f, TraceSnapshotFilter)]
        assert len(snapshot_filters) == 1, (
            "QueueHandler must have exactly one TraceSnapshotFilter so trace_id is "
            "captured in the calling thread before the record enters the async queue."
        )

    def test_queue_path_records_have_correct_trace_id(self):
        """
        Records processed by the background QueueListener must carry the trace_id
        that was active in the *calling* thread at enqueue time.

        Without TraceSnapshotFilter on the QueueHandler the record enters the queue
        without trace_id, and the background thread's TraceFilter reads
        trace_context.get() == None, emitting 'Global'.

        With TraceSnapshotFilter the snapshot runs in the calling thread, sets
        trace_id on the record before it is enqueued, and the background handler
        sees the correct value regardless of which thread it runs in.
        """
        import time
        import queue as stdlib_queue
        from logging.handlers import QueueHandler, QueueListener
        from logcrest.config import TraceSnapshotFilter, TraceFilter

        captured = []

        class CapturingHandler(logging.Handler):
            def emit(self, record):
                captured.append(record)

        # Build an isolated async pipeline: QueueHandler → queue → QueueListener → CapturingHandler
        log_queue = stdlib_queue.Queue(-1)

        queue_handler = QueueHandler(log_queue)
        queue_handler.addFilter(TraceSnapshotFilter())  # the fix being tested

        capture_handler = CapturingHandler()
        capture_handler.addFilter(TraceFilter())  # handles funcName override + fallback

        listener = QueueListener(log_queue, capture_handler, respect_handler_level=True)
        listener.start()

        test_logger = logging.getLogger("queue_path_isolation_logger")
        test_logger.setLevel(logging.DEBUG)
        test_logger.handlers.clear()
        test_logger.addHandler(queue_handler)

        try:
            token = trace_context.set("queue-trace-xyz")
            try:
                test_logger.info("user message through queue")
            finally:
                trace_context.reset(token)

            time.sleep(0.1)
        finally:
            listener.stop()

        assert len(captured) == 1
        assert captured[0].trace_id == "queue-trace-xyz", (
            "Background-thread handler must see trace_id captured at enqueue time "
            "(calling thread), not 'Global'. Without TraceSnapshotFilter on the "
            "QueueHandler, trace_context.get() in the background thread returns None."
        )
