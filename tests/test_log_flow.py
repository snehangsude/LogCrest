"""
TDD tests for @log_flow decorator.

@log_flow is a separate decorator from @log_decorator. It marks a function as a
flow entry point — generates a flow ID, tracks nested @log_decorator calls in a
timeline ContextVar, and emits flow_start / flow_end records on entry / exit.

When called inside an already-active flow (nested @log_flow), it degrades:
no new flow context is created, a UserWarning is emitted, and the function
appears in the outer flow's timeline exactly like a @log_decorator call.

Implementation targets:
  logcrest/flow.py      — new file, log_flow decorator
  logcrest/utils.py     — add flow_id_context, flow_stack_context ContextVars
  logcrest/decorator.py — append to flow_stack_context if active
  logcrest/__init__.py  — export log_flow

Record field names used by @log_flow:
  flow_type    : 'flow_start' | 'flow_end'
  flow_id      : e.g. 'checkout-a1b2c3d4'
  flow_status  : 'success' | 'failed'   (flow_end only)
  total_ms     : float                   (flow_end only)
  steps        : int                     (flow_end only)
  timeline     : list of {fn, ms, status}  (flow_end only)
  failed_at    : str                     (flow_end + failed only)
  step         : 'N/M'                   (flow_end + failed only)
  flow_error   : 'ExcType: msg'          (flow_end + failed only)

Timeline entry status values:
  'ok'          — function completed successfully
  'failed'      — function directly raised the exception
  'interrupted' — function received a re-raised exception from a nested call
"""
import logging
import asyncio
import re
import warnings
import pytest


# ── shared helpers ───────────────────────────────────────────────────────────

def _capture():
    """Returns (handler, records_list). Records have TraceFilter applied."""
    from logcrest.config import TraceFilter
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


def _run(fn, *a, **kw):
    """Run fn(*a, **kw) with capture; swallow any exceptions; return records."""
    h, records = _capture()
    lg = _attach(h)
    try:
        try:
            fn(*a, **kw)
        except Exception:
            pass
    finally:
        _detach(lg, h)
    return records


def _flow_end(records):
    return next((r for r in records if getattr(r, 'flow_type', None) == 'flow_end'), None)


def _flow_start(records):
    return next((r for r in records if getattr(r, 'flow_type', None) == 'flow_start'), None)


# ── Group 1: flow ID generation ──────────────────────────────────────────────

class TestFlowIdGeneration:
    """Flow IDs follow the pattern: [label-]{8 hex chars from uuid4}"""

    def test_bare_decorator_generates_8hex_suffix_only(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context

        seen = []

        @log_flow
        def work():
            seen.append(flow_id_context.get())

        _run(work)
        assert seen, "flow_id_context must be set inside @log_flow"
        assert re.fullmatch(r'[0-9a-f]{8}', seen[0]), (
            f"Bare @log_flow must produce 8 hex chars, got: {seen[0]!r}"
        )

    def test_string_arg_prefixes_id_with_hyphen(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context

        seen = []

        @log_flow("checkout")
        def work():
            seen.append(flow_id_context.get())

        _run(work)
        assert seen[0].startswith("checkout-"), f"Got: {seen[0]!r}"
        suffix = seen[0][len("checkout-"):]
        assert re.fullmatch(r'[0-9a-f]{8}', suffix), f"Suffix not 8 hex: {suffix!r}"

    def test_hyphenated_label_preserved(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context

        seen = []

        @log_flow("api-request")
        def work():
            seen.append(flow_id_context.get())

        _run(work)
        assert seen[0].startswith("api-request-"), f"Got: {seen[0]!r}"

    def test_label_uppercase_is_lowercased(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context

        seen = []

        @log_flow("Checkout")
        def work():
            seen.append(flow_id_context.get())

        _run(work)
        assert seen[0].startswith("checkout-"), f"Uppercase not lowercased: {seen[0]!r}"

    def test_label_invalid_chars_replaced_and_deduplicated(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context

        seen = []

        # "my flow!" → "my-flow" (space→'-', '!'→removed, trailing '-' stripped)
        @log_flow("my flow!")
        def work():
            seen.append(flow_id_context.get())

        _run(work)
        assert seen[0] is not None
        # Must not contain space or '!'
        assert ' ' not in seen[0] and '!' not in seen[0]
        # Must still be a valid label-hex pattern
        parts = seen[0].rsplit('-', 1)
        assert re.fullmatch(r'[0-9a-f]{8}', parts[-1]), f"Suffix malformed: {seen[0]!r}"

    def test_label_from_kwarg_name(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context

        seen = []

        @log_flow(label_from="order_id")
        def process(data, order_id=None):
            seen.append(flow_id_context.get())

        _run(process, data={}, order_id="ord-123")
        assert seen[0].startswith("ord-123-"), f"Got: {seen[0]!r}"

    def test_label_from_positional_index_0(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context

        seen = []

        @log_flow(label_from=0)
        def handle(request_id, payload):
            seen.append(flow_id_context.get())

        _run(handle, "req-abc", {})
        assert seen[0].startswith("req-abc-"), f"Got: {seen[0]!r}"

    def test_label_from_missing_kwarg_falls_back_to_hex_only(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context

        seen = []

        @log_flow(label_from="nonexistent_key")
        def work(data):
            seen.append(flow_id_context.get())

        _run(work, data={})
        assert seen[0] is not None
        assert re.fullmatch(r'[0-9a-f]{8}', seen[0]), (
            f"Missing label_from kwarg must fall back to bare 8-hex ID, got: {seen[0]!r}"
        )

    def test_two_consecutive_calls_produce_different_ids(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context

        ids = []

        @log_flow("checkout")
        def work():
            ids.append(flow_id_context.get())

        _run(work)
        _run(work)
        assert len(ids) == 2
        assert ids[0] != ids[1], "Each call must generate a unique flow ID"


# ── Group 2: context var lifecycle ──────────────────────────────────────────

class TestFlowContext:
    """flow_id_context and flow_stack_context must be set inside the flow and
    reset to None after the call completes (success or exception)."""

    def test_flow_id_accessible_inside_decorated_fn(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context

        seen = []

        @log_flow("auth")
        def work():
            seen.append(flow_id_context.get())

        _run(work)
        assert seen[0] is not None and "auth-" in seen[0]

    def test_flow_id_is_none_outside_any_flow(self):
        from logcrest.utils import flow_id_context
        assert flow_id_context.get() is None

    def test_flow_id_reset_after_successful_call(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context

        @log_flow
        def work():
            pass

        _run(work)
        assert flow_id_context.get() is None

    def test_flow_id_reset_after_exception(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context

        @log_flow
        def work():
            raise RuntimeError("boom")

        _run(work)
        assert flow_id_context.get() is None

    def test_flow_stack_is_none_outside_flow(self):
        from logcrest.utils import flow_stack_context
        assert flow_stack_context.get() is None

    def test_flow_stack_reset_after_successful_call(self):
        from logcrest import log_flow
        from logcrest.utils import flow_stack_context

        @log_flow
        def work():
            pass

        _run(work)
        assert flow_stack_context.get() is None

    def test_flow_stack_reset_after_exception(self):
        from logcrest import log_flow
        from logcrest.utils import flow_stack_context

        @log_flow
        def work():
            raise ValueError("fail")

        _run(work)
        assert flow_stack_context.get() is None


# ── Group 3: records emitted ─────────────────────────────────────────────────

class TestFlowRecords:
    """@log_flow emits exactly one flow_start record on entry and one flow_end
    record on exit (either success or failure)."""

    def test_flow_start_record_emitted_on_entry(self):
        from logcrest import log_flow

        @log_flow
        def work():
            pass

        records = _run(work)
        starts = [r for r in records if getattr(r, 'flow_type', None) == 'flow_start']
        assert len(starts) == 1

    def test_flow_end_success_emitted_on_normal_exit(self):
        from logcrest import log_flow

        @log_flow
        def work():
            pass

        records = _run(work)
        end = _flow_end(records)
        assert end is not None
        assert getattr(end, 'flow_status', None) == 'success'

    def test_flow_end_failed_emitted_on_exception(self):
        from logcrest import log_flow

        @log_flow
        def work():
            raise ValueError("oops")

        records = _run(work)
        end = _flow_end(records)
        assert end is not None
        assert getattr(end, 'flow_status', None) == 'failed'

    def test_flow_end_has_total_ms_float(self):
        from logcrest import log_flow

        @log_flow
        def work():
            pass

        records = _run(work)
        end = _flow_end(records)
        assert hasattr(end, 'total_ms')
        assert isinstance(end.total_ms, (int, float)) and end.total_ms >= 0

    def test_flow_end_has_steps_int(self):
        from logcrest import log_flow

        @log_flow
        def work():
            pass

        records = _run(work)
        end = _flow_end(records)
        assert hasattr(end, 'steps')
        assert isinstance(end.steps, int)

    def test_flow_end_has_timeline_list(self):
        from logcrest import log_flow

        @log_flow
        def work():
            pass

        records = _run(work)
        end = _flow_end(records)
        assert hasattr(end, 'timeline')
        assert isinstance(end.timeline, list)

    def test_flow_end_failure_has_failed_at_matching_raiser(self):
        from logcrest import log_flow, log_decorator

        @log_decorator
        def broken():
            raise ConnectionError("lost")

        @log_flow
        def work():
            broken()

        records = _run(work)
        end = _flow_end(records)
        assert hasattr(end, 'failed_at')
        assert end.failed_at == 'broken'

    def test_flow_end_failure_has_step_fraction(self):
        from logcrest import log_flow, log_decorator

        @log_decorator
        def step1():
            pass

        @log_decorator
        def step2():
            raise RuntimeError("fail here")

        @log_flow
        def work():
            step1()
            step2()

        records = _run(work)
        end = _flow_end(records)
        assert hasattr(end, 'step')
        assert end.step == '2/2', f"Expected '2/2', got: {end.step!r}"

    def test_flow_end_failure_has_flow_error_string(self):
        from logcrest import log_flow

        @log_flow
        def work():
            raise ValueError("specific message here")

        records = _run(work)
        end = _flow_end(records)
        assert hasattr(end, 'flow_error')
        assert 'ValueError' in end.flow_error
        assert 'specific message here' in end.flow_error

    def test_exception_is_reraised_after_flow_end(self):
        from logcrest import log_flow

        @log_flow
        def work():
            raise ValueError("must propagate")

        h, _ = _capture()
        lg = _attach(h)
        try:
            with pytest.raises(ValueError, match="must propagate"):
                work()
        finally:
            _detach(lg, h)

    def test_flow_start_and_end_share_flow_id(self):
        from logcrest import log_flow

        @log_flow("order")
        def work():
            pass

        records = _run(work)
        start = _flow_start(records)
        end = _flow_end(records)
        assert start is not None and end is not None
        assert start.flow_id == end.flow_id
        assert start.flow_id.startswith("order-")

    def test_flow_start_has_flow_id_attribute(self):
        from logcrest import log_flow

        @log_flow("checkout")
        def work():
            pass

        records = _run(work)
        start = _flow_start(records)
        assert hasattr(start, 'flow_id')
        assert start.flow_id.startswith("checkout-")

    def test_flow_end_level_is_error_on_failure(self):
        from logcrest import log_flow

        @log_flow
        def work():
            raise RuntimeError("boom")

        records = _run(work)
        end = _flow_end(records)
        assert end.levelno == logging.ERROR

    def test_flow_start_level_matches_level_param(self):
        from logcrest import log_flow

        @log_flow("test", level=logging.DEBUG)
        def work():
            pass

        h, records = _capture()
        lg = _attach(h)
        lg.setLevel(logging.DEBUG)
        try:
            work()
        finally:
            _detach(lg, h)

        start = _flow_start(records)
        assert start is not None
        assert start.levelno == logging.DEBUG


# ── Group 4: timeline tracking ───────────────────────────────────────────────

class TestFlowTimeline:
    """@log_decorator calls inside a @log_flow appear in the flow_end timeline."""

    def _timeline(self, fn):
        records = _run(fn)
        end = _flow_end(records)
        return end.timeline if end else []

    def test_nested_log_decorator_appears_in_timeline(self):
        from logcrest import log_flow, log_decorator

        @log_decorator
        def inner():
            pass

        @log_flow
        def outer():
            inner()

        tl = self._timeline(outer)
        assert any(e['fn'] == 'inner' for e in tl)

    def test_timeline_entry_has_fn_ms_status_keys(self):
        from logcrest import log_flow, log_decorator

        @log_decorator
        def step():
            pass

        @log_flow
        def work():
            step()

        tl = self._timeline(work)
        assert len(tl) >= 1
        entry = next(e for e in tl if e['fn'] == 'step')
        assert set(entry.keys()) >= {'fn', 'ms', 'status'}

    def test_successful_step_has_status_ok(self):
        from logcrest import log_flow, log_decorator

        @log_decorator
        def good():
            pass

        @log_flow
        def work():
            good()

        tl = self._timeline(work)
        entry = next(e for e in tl if e['fn'] == 'good')
        assert entry['status'] == 'ok'

    def test_failed_step_has_status_failed(self):
        from logcrest import log_flow, log_decorator

        @log_decorator
        def bad():
            raise RuntimeError("direct raise")

        @log_flow
        def work():
            bad()

        tl = self._timeline(work)
        entry = next(e for e in tl if e['fn'] == 'bad')
        assert entry['status'] == 'failed'

    def test_interrupted_step_has_status_interrupted(self):
        """The outer @log_decorator that propagated the exception is 'interrupted',
        not 'failed' — only the function that directly raised is 'failed'."""
        from logcrest import log_flow, log_decorator

        @log_decorator
        def raises():
            raise RuntimeError("inner fails")

        @log_decorator
        def propagates():
            raises()

        @log_flow
        def work():
            propagates()

        tl = self._timeline(work)
        inner_e = next(e for e in tl if e['fn'] == 'raises')
        outer_e = next(e for e in tl if e['fn'] == 'propagates')
        assert inner_e['status'] == 'failed'
        assert outer_e['status'] == 'interrupted'

    def test_timeline_order_matches_call_order(self):
        from logcrest import log_flow, log_decorator

        @log_decorator
        def first():
            pass

        @log_decorator
        def second():
            pass

        @log_decorator
        def third():
            pass

        @log_flow
        def work():
            first()
            second()
            third()

        tl = self._timeline(work)
        fns = [e['fn'] for e in tl]
        assert fns == ['first', 'second', 'third']

    def test_steps_count_equals_timeline_length(self):
        from logcrest import log_flow, log_decorator

        @log_decorator
        def a():
            pass

        @log_decorator
        def b():
            pass

        records = _run(lambda: [a(), b()] if False else None)  # won't trigger flow

        h, records = _capture()
        lg = _attach(h)
        try:
            @log_flow
            def work():
                a()
                b()
            work()
        finally:
            _detach(lg, h)

        end = _flow_end(records)
        assert end.steps == len(end.timeline) == 2

    def test_log_decorator_outside_flow_does_not_modify_stack(self):
        from logcrest import log_decorator
        from logcrest.utils import flow_stack_context

        @log_decorator
        def standalone():
            pass

        standalone()
        assert flow_stack_context.get() is None

    def test_timeline_ms_is_non_negative_float(self):
        from logcrest import log_flow, log_decorator

        @log_decorator
        def step():
            pass

        @log_flow
        def work():
            step()

        tl = self._timeline(work)
        entry = next(e for e in tl if e['fn'] == 'step')
        assert isinstance(entry['ms'], (int, float))
        assert entry['ms'] >= 0


# ── Group 5: nested @log_flow degrades ──────────────────────────────────────

class TestNestedFlow:
    """When @log_flow is used inside an already-active flow it degrades:
    it emits a UserWarning, does not start a new flow, and appears in the
    outer flow's timeline like a @log_decorator call."""

    def test_nested_log_flow_emits_user_warning(self):
        from logcrest import log_flow

        @log_flow
        def inner():
            pass

        inner_warnings = []

        @log_flow
        def outer():
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                inner()
            inner_warnings.extend(w)

        h, _ = _capture()
        lg = _attach(h)
        try:
            outer()
        finally:
            _detach(lg, h)

        assert any("flow" in str(x.message).lower() for x in inner_warnings), (
            "Nested @log_flow must emit a UserWarning mentioning 'flow'"
        )

    def test_only_outer_flow_emits_flow_start(self):
        from logcrest import log_flow

        @log_flow
        def inner():
            pass

        @log_flow
        def outer():
            inner()

        records = _run(outer)
        starts = [r for r in records if getattr(r, 'flow_type', None) == 'flow_start']
        assert len(starts) == 1, f"Expected 1 flow_start, got {len(starts)}"

    def test_only_outer_flow_emits_flow_end(self):
        from logcrest import log_flow

        @log_flow
        def inner():
            pass

        @log_flow
        def outer():
            inner()

        records = _run(outer)
        ends = [r for r in records if getattr(r, 'flow_type', None) == 'flow_end']
        assert len(ends) == 1, f"Expected 1 flow_end, got {len(ends)}"

    def test_degraded_inner_function_appears_in_outer_timeline(self):
        from logcrest import log_flow

        @log_flow
        def inner():
            pass

        @log_flow
        def outer():
            inner()

        records = _run(outer)
        end = _flow_end(records)
        fns = [e['fn'] for e in end.timeline]
        assert 'inner' in fns, f"Degraded inner @log_flow not in timeline: {fns}"

    def test_inner_log_flow_children_appear_in_outer_timeline(self):
        from logcrest import log_flow, log_decorator

        @log_decorator
        def child():
            pass

        @log_flow
        def inner():
            child()

        @log_flow
        def outer():
            inner()

        records = _run(outer)
        end = _flow_end(records)
        fns = [e['fn'] for e in end.timeline]
        assert 'inner' in fns
        assert 'child' in fns


# ── Group 6: async support ───────────────────────────────────────────────────

class TestAsyncFlow:
    """@log_flow works identically on async def functions."""

    def _run_async(self, coro_fn):
        h, records = _capture()
        lg = _attach(h)
        try:
            try:
                asyncio.run(coro_fn())
            except Exception:
                pass
        finally:
            _detach(lg, h)
        return records

    def test_async_bare_decorator_generates_8hex_id(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context

        seen = []

        @log_flow
        async def work():
            seen.append(flow_id_context.get())

        self._run_async(work)
        assert seen[0] is not None
        assert re.fullmatch(r'[0-9a-f]{8}', seen[0]), f"Got: {seen[0]!r}"

    def test_async_label_prefixes_id(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context

        seen = []

        @log_flow("async-checkout")
        async def work():
            seen.append(flow_id_context.get())

        self._run_async(work)
        assert seen[0].startswith("async-checkout-"), f"Got: {seen[0]!r}"

    def test_async_emits_flow_start_and_end(self):
        from logcrest import log_flow

        @log_flow
        async def work():
            pass

        records = self._run_async(work)
        assert any(getattr(r, 'flow_type', None) == 'flow_start' for r in records)
        assert any(getattr(r, 'flow_type', None) == 'flow_end' for r in records)

    def test_async_nested_log_decorator_appears_in_timeline(self):
        from logcrest import log_flow, log_decorator

        @log_decorator
        async def child():
            await asyncio.sleep(0)

        @log_flow
        async def outer():
            await child()

        records = self._run_async(outer)
        end = _flow_end(records)
        assert end is not None
        fns = [e['fn'] for e in end.timeline]
        assert 'child' in fns

    def test_async_flow_failure_has_status_failed(self):
        from logcrest import log_flow

        @log_flow
        async def work():
            raise ValueError("async fail")

        records = self._run_async(work)
        end = _flow_end(records)
        assert end is not None
        assert end.flow_status == 'failed'

    def test_async_return_value_not_swallowed(self):
        from logcrest import log_flow

        @log_flow
        async def work():
            return 42

        result = asyncio.run(work())
        assert result == 42

    def test_async_flow_id_reset_after_call(self):
        from logcrest import log_flow
        from logcrest.utils import flow_id_context

        @log_flow
        async def work():
            pass

        asyncio.run(work())
        assert flow_id_context.get() is None


# ── Group 7: params and return value ─────────────────────────────────────────

class TestFlowParams:
    """@log_flow accepts log_args, log_result, level; never swallows return value."""

    def test_sync_return_value_not_swallowed(self):
        from logcrest import log_flow

        @log_flow
        def work():
            return {"result": 99}

        assert work() == {"result": 99}

    def test_accepts_level_param_applied_to_flow_records(self):
        from logcrest import log_flow

        @log_flow("lvl-test", level=logging.DEBUG)
        def work():
            pass

        h, records = _capture()
        lg = _attach(h)
        original_level = lg.level
        lg.setLevel(logging.DEBUG)
        try:
            work()
        finally:
            lg.setLevel(original_level)
            _detach(lg, h)

        flow_records = [r for r in records if getattr(r, 'flow_type', None) in ('flow_start', 'flow_end')]
        assert len(flow_records) >= 2
        assert all(r.levelno == logging.DEBUG for r in flow_records)

    def test_accepts_log_args_true_includes_args_in_start_message(self):
        from logcrest import log_flow

        @log_flow("argtest", log_args=True)
        def work(x, y):
            pass

        h, records = _capture()
        lg = _attach(h)
        try:
            work(10, 20)
        finally:
            _detach(lg, h)

        start = _flow_start(records)
        assert start is not None
        msg = start.getMessage()
        assert '10' in msg and '20' in msg, (
            f"log_args=True must include positional arg values in flow_start message. Got: {msg!r}"
        )

    def test_no_parens_form_still_returns_correct_value(self):
        from logcrest import log_flow

        @log_flow
        def work():
            return [1, 2, 3]

        assert work() == [1, 2, 3]
