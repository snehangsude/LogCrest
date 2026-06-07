import logging
import contextvars
from .core import AsyncLoggerBuilder

# Global state for trace propagation
trace_context = contextvars.ContextVar("trace_id", default=None)

# Flow tracking — set by @log_flow, read by @log_decorator
flow_id_context = contextvars.ContextVar("flow_id", default=None)
flow_stack_context = contextvars.ContextVar("flow_stack", default=None)

# Singleton logger and its builder.  The builder must be kept alive so the
# QueueListener (now an instance variable on the builder) is not GC-collected.
_internal_logger = None
_internal_builder = None

# Programmatic config set by configure() — highest priority over env vars and JSON file.
_code_config = {}

# Mapping from configure() kwarg names to ConfigManager key names.
_CONFIGURE_KEY_MAP = {
    'dir':          'base_log_dir',
    'json':         'use_json',
    'name':         'log_name',
    'level':        'log_level',
    'max_size':     'max_log_size',
    'backup_count': 'backup_count',
    'queue_size':   'max_queue_size',
}


def configure(*, dir=None, json=None, name=None, level=None, max_size=None,
              backup_count=None, queue_size=None):
    """Configure LogCrest programmatically.

    Must be called before the first log statement for zero-overhead setup, but
    also works after the logger is already built — triggers a clean rebuild.

    Priority: configure() kwargs > env vars > log_config.json > defaults.

    Parameters
    ----------
    dir:
        Base directory for log files (replaces base_log_dir in JSON config).
    json:
        True for JSON-formatted files; False for coloured text.
    name:
        Logger name. Useful when running multiple services in the same process.
    level:
        Minimum log level as a string ("DEBUG", "INFO", "WARNING", "ERROR",
        "CRITICAL") or an int (logging.DEBUG etc.). Controls the logger gate.
    max_size:
        Maximum bytes per rotating log file before rollover.
    backup_count:
        Number of backup log files to retain after rotation.
    queue_size:
        Maximum number of pending records in the async queue. <= 0 (default)
        means unbounded. A positive bound caps memory under sustained overload;
        records are dropped (with a handleError report) when the queue is full.
    """
    global _code_config
    kwargs = {
        'dir': dir, 'json': json, 'name': name, 'level': level,
        'max_size': max_size, 'backup_count': backup_count, 'queue_size': queue_size,
    }
    for kwarg_name, value in kwargs.items():
        if value is not None:
            config_key = _CONFIGURE_KEY_MAP[kwarg_name]
            _code_config[config_key] = value

    if _internal_logger is not None:
        _rebuild()


def _rebuild():
    """Stop the current listener, clear handlers, reset globals for a fresh build."""
    global _internal_logger, _internal_builder
    if _internal_builder is not None and _internal_builder._listener is not None:
        try:
            _internal_builder._listener.stop()
        except Exception:
            pass
    if _internal_builder is not None:
        old_name = _internal_builder.config.get('log_name', 'app_logger')
        logging.getLogger(old_name).handlers.clear()
    _internal_logger = None
    _internal_builder = None


def get_session_logger():
    """Retrieves or creates the global logger instance."""
    global _internal_logger, _internal_builder
    if _internal_logger is None:
        _internal_builder = AsyncLoggerBuilder(overrides=dict(_code_config))
        _internal_logger = _internal_builder.build()
    return _internal_logger


class LogProxy:
    """Passes log calls through to the active logger."""
    def __getattr__(self, name):
        return getattr(get_session_logger(), name)


# Primary entry point for logging
log = LogProxy()
