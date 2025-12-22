import contextvars
from .core import AsyncLoggerBuilder

# Global state for trace propagation
trace_context = contextvars.ContextVar("trace_id", default=None)

# Singleton instance of the logger
_internal_logger = None

def get_session_logger():
    """Retrieves or creates the global logger instance"""
    global _internal_logger
    if _internal_logger is None:
        _internal_logger = AsyncLoggerBuilder().build()
    return _internal_logger

class LogProxy:
    """Passes log calls through to the active logger"""
    def __getattr__(self, name):
        return getattr(get_session_logger(), name)

# Primary entry point for logging
log = LogProxy()
