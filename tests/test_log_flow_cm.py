"""
TDD tests for log_flow as a context manager.

Goal: log_flow("label") and log_flow() must work with both `with` and
`async with`, in addition to their existing decorator behaviour. The same
_FlowContext object must be usable as a decorator (for functions) and as a
context manager (for imperative blocks), and must degrade gracefully when
nested inside an already-active flow.

Implementation targets:
  logcrest/flow.py — _FlowContext class, _wrap_function helper, updated log_flow
"""
import asyncio
import logging
import warnings
import pytest


# ── helpers ──────────────────────────────────────────────────────────────────

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


def _detach(lg, h):
    lg.removeHandler(h)


# ── Group 1: return type ─────────────────────────────────────────────────────

class TestLogFlowReturnType:
    def test_log_flow_with_label_returns_context_manager(self):
        from logcrest import log_flow
        obj = log_flow("my-flow")
        assert hasattr(obj, '__enter__') and hasattr(obj, '__exit__')

    def test_log_flow_no_args_returns_context_manager(self):
        from logcrest import log_flow
        obj = log_flow()
        assert hasattr(obj, '__enter__') and hasattr(obj, '__exit__')

    def test_log_flow_with_label_also_async_context_manager(self):
        from logcrest import log_flow
        obj = log_flow("my-flow")
        assert hasattr(obj, '__aenter__') and hasattr(obj, '__aexit__')

    def test_log_flow_with_label_still_works_as_decorator(self):
        """log_flow("label") must still work as a decorator — no regression."""
        from logcrest import log_flow

        @log_flow("compat")
        def fn():
            return 42

        assert fn() == 42

    def test_log_flow_bare_still_works_as_decorator(self):
        """@log_flow (no parens) must still work — no regression."""
        from logcrest import log_flow

        @log_flow
        def fn():
            return 99

        assert fn() == 99


# ── Group 2: sync context manager ────────────────────────────────────────────

class TestSyncContextManager:
    def test_sync_cm_does_not_raise(self):
        from logcrest import log_flow
        with log_flow("sync-test"):
            pass

    def test_sync_cm_body_executes(self):
        from logcrest import log_flow
        executed = []
        with log_flow("exec-test"):
            executed.append(True)
        assert executed == [True]

    def test_sync_cm_emits_flow_start(self):
        from logcrest import log_flow
        lg, h, records = _capture()
        try:
            with log_flow("start-test"):
                pass
        finally:
            _detach(lg, h)
        starts = [r for r in records if getattr(r, 'flow_type', None) == 'flow_start']
        assert len(starts) == 1

    def test_sync_cm_emits_flow_end_success(self):
        from logcrest import log_flow
        lg, h, records = _capture()
        try:
            with log_flow("end-test"):
                pass
        finally:
            _detach(lg, h)
        ends = [r for r in records if getattr(r, 'flow_type', None) == 'flow_end']
        assert len(ends) == 1
        assert ends[0].flow_status == 'success'

    def test_sync_cm_emits_flow_end_failed_on_exception(self):
        from logcrest import log_flow
        lg, h, records = _capture()
        try:
            with log_flow("fail-test"):
                raise ValueError("boom")
        except ValueError:
            pass
        finally:
            _detach(lg, h)
        ends = [r for r in records if getattr(r, 'flow_type', None) == 'flow_end']
        assert len(ends) == 1
        assert ends[0].flow_status == 'failed'

    def test_sync_cm_does_not_suppress_exceptions(self):
        from logcrest import log_flow
        with pytest.raises(RuntimeError, match="should propagate"):
            with log_flow("suppress-test"):
                raise RuntimeError("should propagate")

    def test_sync_cm_label_appears_in_flow_id(self):
        from logcrest import log_flow
        lg, h, records = _capture()
        try:
            with log_flow("checkout"):
                pass
        finally:
            _detach(lg, h)
        start = next(r for r in records if getattr(r, 'flow_type', None) == 'flow_start')
        assert start.flow_id.startswith("checkout-")

    def test_sync_cm_no_label_generates_bare_hex_id(self):
        import re
        from logcrest import log_flow
        lg, h, records = _capture()
        try:
            with log_flow():
                pass
        finally:
            _detach(lg, h)
        start = next(r for r in records if getattr(r, 'flow_type', None) == 'flow_start')
        assert re.fullmatch(r'[0-9a-f]{8}', start.flow_id)

    def test_sync_cm_sets_flow_id_context_inside_block(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context
        seen = []
        with log_flow("ctx-test"):
            seen.append(flow_id_context.get())
        assert seen[0] is not None

    def test_sync_cm_resets_flow_id_context_after_exit(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context
        with log_flow("reset-test"):
            pass
        assert flow_id_context.get() is None

    def test_sync_cm_resets_context_even_on_exception(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context
        try:
            with log_flow("exc-reset"):
                raise ValueError("x")
        except ValueError:
            pass
        assert flow_id_context.get() is None

    def test_sync_cm_start_and_end_share_flow_id(self):
        from logcrest import log_flow
        lg, h, records = _capture()
        try:
            with log_flow("shared-id"):
                pass
        finally:
            _detach(lg, h)
        start = next(r for r in records if getattr(r, 'flow_type', None) == 'flow_start')
        end = next(r for r in records if getattr(r, 'flow_type', None) == 'flow_end')
        assert start.flow_id == end.flow_id

    def test_sync_cm_end_has_total_ms(self):
        from logcrest import log_flow
        lg, h, records = _capture()
        try:
            with log_flow("ms-test"):
                pass
        finally:
            _detach(lg, h)
        end = next(r for r in records if getattr(r, 'flow_type', None) == 'flow_end')
        assert hasattr(end, 'total_ms') and end.total_ms >= 0

    def test_sync_cm_end_has_timeline_list(self):
        from logcrest import log_flow
        lg, h, records = _capture()
        try:
            with log_flow("tl-test"):
                pass
        finally:
            _detach(lg, h)
        end = next(r for r in records if getattr(r, 'flow_type', None) == 'flow_end')
        assert isinstance(end.timeline, list)

    def test_sync_cm_log_decorator_inside_appears_in_timeline(self):
        from logcrest import log_flow, log_decorator
        lg, h, records = _capture()

        @log_decorator
        def step():
            return "done"

        try:
            with log_flow("tl-step"):
                step()
        finally:
            _detach(lg, h)

        end = next(r for r in records if getattr(r, 'flow_type', None) == 'flow_end')
        assert any(e['fn'] == 'step' for e in end.timeline)

    def test_sync_cm_failed_step_shows_in_timeline(self):
        from logcrest import log_flow, log_decorator
        lg, h, records = _capture()

        @log_decorator
        def bad_step():
            raise ValueError("fail")

        try:
            with log_flow("fail-step"):
                bad_step()
        except ValueError:
            pass
        finally:
            _detach(lg, h)

        end = next(r for r in records if getattr(r, 'flow_type', None) == 'flow_end')
        entry = next((e for e in end.timeline if e['fn'] == 'bad_step'), None)
        assert entry is not None and entry['status'] == 'failed'


# ── Group 3: async context manager ───────────────────────────────────────────

class TestAsyncContextManager:
    def test_async_cm_does_not_raise(self):
        from logcrest import log_flow
        async def run():
            async with log_flow("async-test"):
                pass
        asyncio.run(run())

    def test_async_cm_body_executes(self):
        from logcrest import log_flow
        executed = []
        async def run():
            async with log_flow("async-exec"):
                executed.append(True)
        asyncio.run(run())
        assert executed == [True]

    def test_async_cm_emits_flow_start(self):
        from logcrest import log_flow
        async def run():
            lg, h, records = _capture()
            try:
                async with log_flow("async-start"):
                    pass
            finally:
                _detach(lg, h)
            return records
        records = asyncio.run(run())
        starts = [r for r in records if getattr(r, 'flow_type', None) == 'flow_start']
        assert len(starts) == 1

    def test_async_cm_emits_flow_end_success(self):
        from logcrest import log_flow
        async def run():
            lg, h, records = _capture()
            try:
                async with log_flow("async-end"):
                    pass
            finally:
                _detach(lg, h)
            return records
        records = asyncio.run(run())
        ends = [r for r in records if getattr(r, 'flow_type', None) == 'flow_end']
        assert len(ends) == 1
        assert ends[0].flow_status == 'success'

    def test_async_cm_emits_flow_end_failed_on_exception(self):
        from logcrest import log_flow
        async def run():
            lg, h, records = _capture()
            try:
                async with log_flow("async-fail"):
                    raise ValueError("async boom")
            except ValueError:
                pass
            finally:
                _detach(lg, h)
            return records
        records = asyncio.run(run())
        ends = [r for r in records if getattr(r, 'flow_type', None) == 'flow_end']
        assert len(ends) == 1
        assert ends[0].flow_status == 'failed'

    def test_async_cm_does_not_suppress_exceptions(self):
        from logcrest import log_flow
        async def run():
            async with log_flow("async-suppress"):
                raise RuntimeError("must propagate")
        with pytest.raises(RuntimeError, match="must propagate"):
            asyncio.run(run())

    def test_async_cm_sets_flow_id_context_inside_block(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context
        seen = []
        async def run():
            async with log_flow("async-ctx"):
                seen.append(flow_id_context.get())
        asyncio.run(run())
        assert seen[0] is not None

    def test_async_cm_resets_flow_id_context_after_exit(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context
        async def run():
            async with log_flow("async-reset"):
                pass
        asyncio.run(run())
        assert flow_id_context.get() is None

    def test_async_cm_resets_context_even_on_exception(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context
        async def run():
            try:
                async with log_flow("async-exc-reset"):
                    raise ValueError("x")
            except ValueError:
                pass
        asyncio.run(run())
        assert flow_id_context.get() is None

    def test_async_cm_label_appears_in_flow_id(self):
        from logcrest import log_flow
        async def run():
            lg, h, records = _capture()
            try:
                async with log_flow("payment"):
                    pass
            finally:
                _detach(lg, h)
            return records
        records = asyncio.run(run())
        start = next(r for r in records if getattr(r, 'flow_type', None) == 'flow_start')
        assert start.flow_id.startswith("payment-")

    def test_async_cm_log_decorator_inside_appears_in_timeline(self):
        from logcrest import log_flow, log_decorator
        async def run():
            lg, h, records = _capture()

            @log_decorator
            async def async_step():
                await asyncio.sleep(0)
                return "ok"

            try:
                async with log_flow("async-tl"):
                    await async_step()
            finally:
                _detach(lg, h)
            return records

        records = asyncio.run(run())
        end = next(r for r in records if getattr(r, 'flow_type', None) == 'flow_end')
        assert any(e['fn'] == 'async_step' for e in end.timeline)

    def test_async_cm_concurrent_gather_steps_in_timeline(self):
        from logcrest import log_flow, log_decorator
        async def run():
            lg, h, records = _capture()

            @log_decorator
            async def step_a():
                await asyncio.sleep(0)

            @log_decorator
            async def step_b():
                await asyncio.sleep(0)

            try:
                async with log_flow("async-gather"):
                    await asyncio.gather(step_a(), step_b())
            finally:
                _detach(lg, h)
            return records

        records = asyncio.run(run())
        end = next(r for r in records if getattr(r, 'flow_type', None) == 'flow_end')
        fns = {e['fn'] for e in end.timeline}
        assert 'step_a' in fns and 'step_b' in fns


# ── Group 4: nested CM inside active flow degrades ────────────────────────────

class TestNestedCmDegrades:
    def test_nested_sync_cm_emits_warning(self):
        from logcrest import log_flow
        lg, h, records = _capture()
        try:
            with log_flow("outer"):
                with warnings.catch_warnings(record=True) as w:
                    warnings.simplefilter("always")
                    with log_flow("inner"):
                        pass
        finally:
            _detach(lg, h)
        assert any("active flow" in str(warning.message) for warning in w)

    def test_nested_sync_cm_does_not_emit_second_flow_start(self):
        from logcrest import log_flow
        lg, h, records = _capture()
        try:
            with log_flow("outer-degrade"):
                with warnings.catch_warnings(record=True):
                    warnings.simplefilter("always")
                    with log_flow("inner-degrade"):
                        pass
        finally:
            _detach(lg, h)
        starts = [r for r in records if getattr(r, 'flow_type', None) == 'flow_start']
        assert len(starts) == 1, f"Expected 1 flow_start, got {len(starts)}"

    def test_nested_sync_cm_does_not_emit_second_flow_end(self):
        from logcrest import log_flow
        lg, h, records = _capture()
        try:
            with log_flow("outer-end"):
                with warnings.catch_warnings(record=True):
                    warnings.simplefilter("always")
                    with log_flow("inner-end"):
                        pass
        finally:
            _detach(lg, h)
        ends = [r for r in records if getattr(r, 'flow_type', None) == 'flow_end']
        assert len(ends) == 1, f"Expected 1 flow_end, got {len(ends)}"

    def test_nested_async_cm_emits_warning(self):
        from logcrest import log_flow
        async def run():
            lg, h, records = _capture()
            caught = []
            try:
                async with log_flow("outer-async"):
                    with warnings.catch_warnings(record=True) as w:
                        warnings.simplefilter("always")
                        async with log_flow("inner-async"):
                            pass
                    caught.extend(w)
            finally:
                _detach(lg, h)
            return caught
        w = asyncio.run(run())
        assert any("active flow" in str(warning.message) for warning in w)
