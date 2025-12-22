import logging
import uuid
import time
from functools import wraps
from .utils import log, trace_context

# Standard log levels
DEBUG = logging.DEBUG
INFO = logging.INFO
WARNING = logging.WARNING
ERROR = logging.ERROR
CRITICAL = logging.CRITICAL

def log_decorator(arg=None):
    """Wraps functions to add tracing, timing, and error logging"""
    
    # Handle both @log_decorator and @log_decorator(LEVEL)
    if callable(arg):
        level = INFO
        func_to_wrap = arg
    else:
        level = arg if arg is not None else INFO
        func_to_wrap = None

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Reuse existing trace or start a new one
            existing_trace = trace_context.get()
            trace_id = existing_trace if existing_trace else str(uuid.uuid4())[:8]
            
            # Mark nested calls
            is_root = not bool(existing_trace)
            if is_root:
                token = trace_context.set(trace_id)
            
            # Context info for handlers
            log_extra = {
                'actual_func_name': func.__name__,
                'trace_id': trace_id
            }

            prefix = "[Root] " if is_root else "[Nested] "
            log.log(level, f"{prefix}Invoking '{func.__name__}' | args={args} kwargs={kwargs}", extra=log_extra)

            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                log.log(level, f"{prefix}'{func.__name__}' finished in {elapsed:.2f}ms | result={result}", extra=log_extra)
                return result
            
            except Exception as e:
                elapsed = (time.perf_counter() - start) * 1000
                log.error(f"{prefix}'{func.__name__}' crashed after {elapsed:.2f}ms | Error: {e}", extra=log_extra, exc_info=True)
                raise
            finally:
                # Clear trace context at the end of root call
                if is_root:
                    trace_context.reset(token)
        return wrapper

    return decorator(func_to_wrap) if func_to_wrap else decorator
