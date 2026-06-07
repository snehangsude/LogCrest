import inspect
import logging
import uuid
import time
import asyncio
from functools import wraps
from .utils import log, trace_context, flow_stack_context

DEBUG = logging.DEBUG
INFO = logging.INFO
WARNING = logging.WARNING
ERROR = logging.ERROR
CRITICAL = logging.CRITICAL


def _setup_trace():
    existing = trace_context.get()
    trace_id = existing if existing else str(uuid.uuid4())[:8]
    is_root = not bool(existing)
    token = trace_context.set(trace_id) if is_root else None
    return trace_id, is_root, token


def _stack_enter(fn_name):
    """Append a 'running' entry to the flow stack if a flow is active.
    Returns (stack, idx) so the caller can update the entry on exit."""
    stack = flow_stack_context.get()
    if stack is None:
        return None, None
    idx = len(stack)
    stack.append({'fn': fn_name, 'status': 'running'})
    return stack, idx


def _stack_ok(stack, idx, elapsed_ms):
    if stack is not None:
        stack[idx]['ms'] = round(elapsed_ms, 2)
        stack[idx]['status'] = 'ok'


def _stack_err(stack, idx, elapsed_ms, exc):
    if stack is not None:
        stack[idx]['ms'] = round(elapsed_ms, 2)
        if not getattr(exc, '_logcrest_flow_registered', False):
            exc._logcrest_flow_registered = True
            stack[idx]['status'] = 'failed'
        else:
            stack[idx]['status'] = 'interrupted'


def log_decorator(arg=None, *, log_args=False, log_result=False):
    """Wraps sync and async functions with tracing, timing, and error logging.

    log_args=False by default — set True only for functions that never receive
    sensitive data (passwords, tokens, PII). Args are logged verbatim.
    log_result=False by default — same caution applies to return values.
    """
    if callable(arg):
        level = INFO
        func_to_wrap = arg
    else:
        level = arg if arg is not None else INFO
        func_to_wrap = None

    def decorator(func):
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                trace_id, is_root, token = _setup_trace()
                log_extra = {'actual_func_name': func.__name__, 'trace_id': trace_id}
                prefix = "[Root] " if is_root else "[Nested] "

                entry_msg = f"{prefix}Invoking '{func.__name__}'"
                if log_args:
                    entry_msg += f" | args={args} kwargs={kwargs}"
                log.log(level, entry_msg, extra=log_extra)

                start = time.perf_counter()
                stack, idx = _stack_enter(func.__name__)
                try:
                    result = await func(*args, **kwargs)
                    elapsed = (time.perf_counter() - start) * 1000
                    _stack_ok(stack, idx, elapsed)
                    exit_msg = f"{prefix}'{func.__name__}' finished in {elapsed:.2f}ms"
                    if log_result:
                        exit_msg += f" | result={result}"
                    log.log(level, exit_msg, extra=log_extra)
                    return result
                except Exception as e:
                    elapsed = (time.perf_counter() - start) * 1000
                    _stack_err(stack, idx, elapsed, e)
                    log.error(
                        f"{prefix}'{func.__name__}' crashed after {elapsed:.2f}ms | Error: {e}",
                        extra=log_extra, exc_info=True
                    )
                    raise
                finally:
                    if is_root:
                        trace_context.reset(token)
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                trace_id, is_root, token = _setup_trace()
                log_extra = {'actual_func_name': func.__name__, 'trace_id': trace_id}
                prefix = "[Root] " if is_root else "[Nested] "

                entry_msg = f"{prefix}Invoking '{func.__name__}'"
                if log_args:
                    entry_msg += f" | args={args} kwargs={kwargs}"
                log.log(level, entry_msg, extra=log_extra)

                start = time.perf_counter()
                stack, idx = _stack_enter(func.__name__)
                try:
                    result = func(*args, **kwargs)
                    elapsed = (time.perf_counter() - start) * 1000
                    _stack_ok(stack, idx, elapsed)
                    exit_msg = f"{prefix}'{func.__name__}' finished in {elapsed:.2f}ms"
                    if log_result:
                        exit_msg += f" | result={result}"
                    log.log(level, exit_msg, extra=log_extra)
                    return result
                except Exception as e:
                    elapsed = (time.perf_counter() - start) * 1000
                    _stack_err(stack, idx, elapsed, e)
                    log.error(
                        f"{prefix}'{func.__name__}' crashed after {elapsed:.2f}ms | Error: {e}",
                        extra=log_extra, exc_info=True
                    )
                    raise
                finally:
                    if is_root:
                        trace_context.reset(token)
            return sync_wrapper

    return decorator(func_to_wrap) if func_to_wrap else decorator
