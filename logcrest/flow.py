import uuid
import re
import time
import inspect
import warnings
import logging
from functools import wraps
from .utils import log, flow_id_context, flow_stack_context, trace_context

_LABEL_RE = re.compile(r'[^a-z0-9-]+')
_MAX_LABEL = 32


def _clean_label(raw):
    cleaned = _LABEL_RE.sub('-', raw.lower()).strip('-')
    cleaned = re.sub(r'-+', '-', cleaned)
    if not cleaned:
        return None
    return cleaned[:_MAX_LABEL].rstrip('-') or None


def _make_flow_id(label):
    suffix = uuid.uuid4().hex[:8]
    if not label:
        return suffix
    clean = _clean_label(label)
    return f"{clean}-{suffix}" if clean else suffix


def _resolve_label(static_label, label_from, args, kwargs):
    if label_from is not None:
        if isinstance(label_from, int):
            try:
                return str(args[label_from])
            except (IndexError, TypeError):
                return None
        if isinstance(label_from, str):
            return str(kwargs[label_from]) if label_from in kwargs else None
    return static_label


def _clean_tl(stack):
    return [{'fn': e['fn'], 'ms': e.get('ms', 0.0), 'status': e['status']} for e in stack]


def _emit_start(fn_name, flow_id, level, log_args, args, kwargs):
    msg = f"[Flow Start] '{fn_name}' | flow_id={flow_id}"
    if log_args:
        msg += f" | args={args} kwargs={kwargs}"
    log.log(level, msg, extra={
        'actual_func_name': fn_name,
        'trace_id': flow_id[:8],
        'flow_id': flow_id,
        'flow_type': 'flow_start',
    })


def _emit_end_success(fn_name, flow_id, level, elapsed_ms, stack):
    tl = _clean_tl(stack)
    log.log(level, f"[Flow End OK] '{fn_name}' | {elapsed_ms:.0f}ms | {len(tl)} steps", extra={
        'actual_func_name': fn_name,
        'trace_id': flow_id[:8],
        'flow_id': flow_id,
        'flow_type': 'flow_end',
        'flow_status': 'success',
        'total_ms': round(elapsed_ms, 2),
        'steps': len(tl),
        'timeline': tl,
    })


def _emit_end_failure(fn_name, flow_id, elapsed_ms, stack, exc):
    for e in stack:
        if e['status'] == 'running':
            e['status'] = 'interrupted'
            e.setdefault('ms', round(elapsed_ms, 2))
    tl = _clean_tl(stack)
    failed = next((e for e in tl if e['status'] == 'failed'), None)
    failed_at = failed['fn'] if failed else fn_name
    step_n = (tl.index(failed) + 1) if failed else 0
    log.error(
        f"[Flow End FAIL] '{fn_name}' | failed at '{failed_at}' step {step_n}/{len(tl)} | {elapsed_ms:.0f}ms",
        extra={
            'actual_func_name': fn_name,
            'trace_id': flow_id[:8],
            'flow_id': flow_id,
            'flow_type': 'flow_end',
            'flow_status': 'failed',
            'total_ms': round(elapsed_ms, 2),
            'steps': len(tl),
            'failed_at': failed_at,
            'step': f'{step_n}/{len(tl)}',
            'flow_error': f'{type(exc).__name__}: {exc}',
            'timeline': tl,
        }
    )


def _degrade_sync(func, active_id, stack, level, log_args, args, kwargs):
    fn = func.__name__
    extra = {'actual_func_name': fn, 'trace_id': active_id[:8]}
    msg = f"[Nested] Invoking '{fn}'"
    if log_args:
        msg += f" | args={args} kwargs={kwargs}"
    log.log(level, msg, extra=extra)

    t0 = time.perf_counter()
    idx = len(stack)
    stack.append({'fn': fn, 'status': 'running'})
    try:
        result = func(*args, **kwargs)
        elapsed = (time.perf_counter() - t0) * 1000
        stack[idx]['ms'] = round(elapsed, 2)
        stack[idx]['status'] = 'ok'
        log.log(level, f"[Nested] '{fn}' finished in {elapsed:.2f}ms", extra=extra)
        return result
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        stack[idx]['ms'] = round(elapsed, 2)
        if not getattr(e, '_logcrest_flow_registered', False):
            e._logcrest_flow_registered = True
            stack[idx]['status'] = 'failed'
        else:
            stack[idx]['status'] = 'interrupted'
        log.error(f"[Nested] '{fn}' crashed after {elapsed:.2f}ms | Error: {e}", extra=extra, exc_info=True)
        raise


async def _degrade_async(func, active_id, stack, level, log_args, args, kwargs):
    fn = func.__name__
    extra = {'actual_func_name': fn, 'trace_id': active_id[:8]}
    msg = f"[Nested] Invoking '{fn}'"
    if log_args:
        msg += f" | args={args} kwargs={kwargs}"
    log.log(level, msg, extra=extra)

    t0 = time.perf_counter()
    idx = len(stack)
    stack.append({'fn': fn, 'status': 'running'})
    try:
        result = await func(*args, **kwargs)
        elapsed = (time.perf_counter() - t0) * 1000
        stack[idx]['ms'] = round(elapsed, 2)
        stack[idx]['status'] = 'ok'
        log.log(level, f"[Nested] '{fn}' finished in {elapsed:.2f}ms", extra=extra)
        return result
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        stack[idx]['ms'] = round(elapsed, 2)
        if not getattr(e, '_logcrest_flow_registered', False):
            e._logcrest_flow_registered = True
            stack[idx]['status'] = 'failed'
        else:
            stack[idx]['status'] = 'interrupted'
        log.error(f"[Nested] '{fn}' crashed after {elapsed:.2f}ms | Error: {e}", extra=extra, exc_info=True)
        raise


def _wrap_function(func, *, static_label, label_from, log_args, log_result, level):
    """Wrap a single function with flow tracking (decorator behaviour)."""
    if inspect.iscoroutinefunction(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            active_id = flow_id_context.get()
            if active_id is not None:
                warnings.warn(
                    f"LogCrest: @log_flow on '{func.__name__}' is inside an active flow "
                    "— degrading to @log_decorator. Only the outermost @log_flow emits flow records.",
                    UserWarning, stacklevel=2,
                )
                outer = flow_stack_context.get()
                return await _degrade_async(func, active_id, outer if outer is not None else [], level, log_args, args, kwargs)

            label = _resolve_label(static_label, label_from, args, kwargs)
            flow_id = _make_flow_id(label)
            stack = []
            fid_tok = flow_id_context.set(flow_id)
            stk_tok = flow_stack_context.set(stack)
            trc_tok = trace_context.set(flow_id[:8])
            _emit_start(func.__name__, flow_id, level, log_args, args, kwargs)
            t0 = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                elapsed = (time.perf_counter() - t0) * 1000
                _emit_end_success(func.__name__, flow_id, level, elapsed, stack)
                return result
            except Exception as exc:
                elapsed = (time.perf_counter() - t0) * 1000
                _emit_end_failure(func.__name__, flow_id, elapsed, stack, exc)
                raise
            finally:
                flow_id_context.reset(fid_tok)
                flow_stack_context.reset(stk_tok)
                trace_context.reset(trc_tok)

        return async_wrapper
    else:
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            active_id = flow_id_context.get()
            if active_id is not None:
                warnings.warn(
                    f"LogCrest: @log_flow on '{func.__name__}' is inside an active flow "
                    "— degrading to @log_decorator. Only the outermost @log_flow emits flow records.",
                    UserWarning, stacklevel=2,
                )
                outer = flow_stack_context.get()
                return _degrade_sync(func, active_id, outer if outer is not None else [], level, log_args, args, kwargs)

            label = _resolve_label(static_label, label_from, args, kwargs)
            flow_id = _make_flow_id(label)
            stack = []
            fid_tok = flow_id_context.set(flow_id)
            stk_tok = flow_stack_context.set(stack)
            trc_tok = trace_context.set(flow_id[:8])
            _emit_start(func.__name__, flow_id, level, log_args, args, kwargs)
            t0 = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                elapsed = (time.perf_counter() - t0) * 1000
                _emit_end_success(func.__name__, flow_id, level, elapsed, stack)
                return result
            except Exception as exc:
                elapsed = (time.perf_counter() - t0) * 1000
                _emit_end_failure(func.__name__, flow_id, elapsed, stack, exc)
                raise
            finally:
                flow_id_context.reset(fid_tok)
                flow_stack_context.reset(stk_tok)
                trace_context.reset(trc_tok)

        return sync_wrapper


class _FlowContext:
    """Returned by log_flow("label") or log_flow() — works as both a decorator and a context manager.

    As a decorator:
        @log_flow("checkout")
        def process(): ...

    As a sync context manager:
        with log_flow("checkout"):
            process()

    As an async context manager:
        async with log_flow("checkout"):
            await process()

    Nested inside an active flow: emits UserWarning and degrades to passive tracking
    (adds to the outer timeline, emits no new flow_start / flow_end).
    """

    def __init__(self, static_label, label_from, log_args, log_result, level):
        self._static_label = static_label
        self._label_from = label_from
        self._log_args = log_args
        self._log_result = log_result
        self._level = level

    def __call__(self, func):
        return _wrap_function(
            func,
            static_label=self._static_label,
            label_from=self._label_from,
            log_args=self._log_args,
            log_result=self._log_result,
            level=self._level,
        )

    # ── context manager internals ─────────────────────────────────────────────

    def _cm_enter(self):
        active_id = flow_id_context.get()
        if active_id is not None:
            warnings.warn(
                "LogCrest: log_flow context manager is inside an active flow "
                "— degrading to passive tracking. Only the outermost flow emits flow records.",
                UserWarning, stacklevel=3,
            )
            outer = flow_stack_context.get()
            outer_stack = outer if outer is not None else []
            idx = len(outer_stack)
            label = self._static_label or 'flow_context'
            outer_stack.append({'fn': label, 'status': 'running'})
            self._cm_state = {
                'degraded': True,
                'stack': outer_stack,
                'idx': idx,
                't0': time.perf_counter(),
            }
            return self

        label = self._static_label or ''
        flow_id = _make_flow_id(label)
        stack = []
        fid_tok = flow_id_context.set(flow_id)
        stk_tok = flow_stack_context.set(stack)
        trc_tok = trace_context.set(flow_id[:8])
        _emit_start(label or flow_id, flow_id, self._level, self._log_args, (), {})
        self._cm_state = {
            'degraded': False,
            'flow_id': flow_id,
            'stack': stack,
            'label': label or flow_id,
            'fid_tok': fid_tok,
            'stk_tok': stk_tok,
            'trc_tok': trc_tok,
            't0': time.perf_counter(),
        }
        return self

    def _cm_exit(self, exc_val):
        state = self._cm_state
        elapsed = (time.perf_counter() - state['t0']) * 1000

        if state['degraded']:
            idx = state['idx']
            outer_stack = state['stack']
            if idx < len(outer_stack):
                outer_stack[idx]['ms'] = round(elapsed, 2)
                if exc_val is None:
                    outer_stack[idx]['status'] = 'ok'
                elif not getattr(exc_val, '_logcrest_flow_registered', False):
                    exc_val._logcrest_flow_registered = True
                    outer_stack[idx]['status'] = 'failed'
                else:
                    outer_stack[idx]['status'] = 'interrupted'
            return

        if exc_val is None:
            _emit_end_success(state['label'], state['flow_id'], self._level, elapsed, state['stack'])
        else:
            _emit_end_failure(state['label'], state['flow_id'], elapsed, state['stack'], exc_val)
        flow_id_context.reset(state['fid_tok'])
        flow_stack_context.reset(state['stk_tok'])
        trace_context.reset(state['trc_tok'])

    def __enter__(self):
        return self._cm_enter()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._cm_exit(exc_val)
        return False

    async def __aenter__(self):
        return self._cm_enter()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._cm_exit(exc_val)
        return False


def log_flow(arg=None, *, label_from=None, log_args=False, log_result=False, level=logging.INFO):
    """Marks a function as a flow entry point, or wraps an imperative block.

    Works as a decorator (for functions) and as a sync/async context manager
    (for imperative code blocks). Both forms generate a unique flow ID, track
    nested @log_decorator calls in a timeline ContextVar, and emit structured
    flow_start / flow_end records.

    When nested inside an already-active flow, degrades gracefully: emits a
    UserWarning, adds to the outer timeline, and does not start a new flow context.

    Decorator forms:
        @log_flow
        @log_flow("label")
        @log_flow("order", log_args=True, level=logging.DEBUG)
        @log_flow(label_from="request_id")
        @log_flow(label_from=0)

    Context manager forms:
        with log_flow("checkout"):
            charge(amount)

        async with log_flow("checkout"):
            await charge(amount)

        with log_flow():          # bare hex ID
            ...
    """
    if callable(arg):
        # @log_flow — bare, no parens — wrap the function directly
        return _wrap_function(
            arg,
            static_label=None,
            label_from=label_from,
            log_args=log_args,
            log_result=log_result,
            level=level,
        )

    # @log_flow("label") / @log_flow() / with log_flow("label"): / with log_flow():
    static_label = arg if isinstance(arg, str) else None
    return _FlowContext(
        static_label=static_label,
        label_from=label_from,
        log_args=log_args,
        log_result=log_result,
        level=level,
    )
