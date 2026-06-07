import os
import logging
import json
import warnings
from pathlib import Path


_KNOWN_KEYS = {
    "base_log_dir", "max_log_size", "backup_count", "use_json",
    "log_name", "log_level", "max_queue_size",
}

_ENV_MAP = {
    "log_name":       "LOGCREST_NAME",
    "base_log_dir":   "LOGCREST_DIR",
    "use_json":       "LOGCREST_JSON",
    "max_log_size":   "LOGCREST_MAX_SIZE",
    "backup_count":   "LOGCREST_BACKUP_COUNT",
    "log_level":      "LOGCREST_LEVEL",
    "max_queue_size": "LOGCREST_QUEUE_SIZE",
}


class LevelFilter(logging.Filter):
    """Restricts logs to a specific level range"""
    def __init__(self, min_level, max_level):
        super().__init__()
        self.min_level = min_level
        self.max_level = max_level

    def filter(self, record):
        return self.min_level <= record.levelno <= self.max_level


class TraceSnapshotFilter(logging.Filter):
    """Captures trace_id from the *calling thread's* contextvars before enqueueing.

    Must be attached to the QueueHandler so it runs in the original calling thread.
    The background thread that the QueueListener uses has its own empty contextvars
    context, so any filter attached to downstream handlers cannot read the caller's
    trace_context.  Snapshotting here, before emit(), guarantees the record already
    carries the correct trace_id by the time the background thread processes it.
    """
    def filter(self, record):
        if not hasattr(record, 'trace_id'):
            from .utils import trace_context  # lazy import — avoids circular dependency
            record.trace_id = trace_context.get() or "Global"
        return True


class FlowFilter(logging.Filter):
    """Passes only flow_start and flow_end records to the flows/ handler."""
    def filter(self, record):
        return getattr(record, 'flow_type', None) in ('flow_start', 'flow_end')


class NoFlowFilter(logging.Filter):
    """Blocks flow records from success/ and error/ handlers."""
    def filter(self, record):
        return getattr(record, 'flow_type', None) not in ('flow_start', 'flow_end')


class TraceFilter(logging.Filter):
    """Ensures trace_id exists on every record and handles function name overrides.

    Runs on downstream handlers (file, console) in the background thread.
    By the time these handlers run, trace_id is already set by TraceSnapshotFilter
    on the QueueHandler; the hasattr guard preserves that value.  The fallback to
    'Global' covers any records that bypass the queue (e.g. direct handler tests).
    """
    def filter(self, record):
        if not hasattr(record, 'trace_id'):
            from .utils import trace_context  # lazy import — avoids circular dependency
            record.trace_id = trace_context.get() or "Global"
        if hasattr(record, 'actual_func_name'):
            record.funcName = record.actual_func_name
        return True


class ConfigManager:
    """Loads and validates log configuration from JSON.

    Resolution order for each key: code overrides > env var > JSON file > caller-supplied default.
    Unknown keys in the JSON file emit a UserWarning so typos surface early.
    """
    def __init__(self, path="log_config.json", overrides=None):
        self.path = Path(path)
        self._overrides = overrides or {}
        self.data = self._load()

    def _load(self):
        if not self.path.exists():
            return {}
        try:
            with open(self.path, 'r') as f:
                data = json.load(f)
            for key in data:
                if key not in _KNOWN_KEYS:
                    warnings.warn(
                        f"LogCrest: unknown config key '{key}' in '{self.path}' — ignored.",
                        UserWarning,
                        stacklevel=3,
                    )
            return data
        except json.JSONDecodeError as e:
            warnings.warn(
                f"LogCrest: '{self.path}' contains invalid JSON ({e}). Using defaults.",
                stacklevel=3,
            )
            return {}
        except OSError as e:
            warnings.warn(
                f"LogCrest: Could not read '{self.path}' ({e}). Using defaults.",
                stacklevel=3,
            )
            return {}

    def get(self, key, default):
        if key in self._overrides:
            return self._overrides[key]
        env_key = _ENV_MAP.get(key)
        if env_key:
            raw = os.environ.get(env_key)
            if raw is not None:
                return self._coerce(key, raw)
        return self.data.get(key, default)

    def _coerce(self, key, raw):
        """Convert env var strings to the expected Python type for each key."""
        if key == "use_json":
            return raw.lower() not in ("false", "0", "no")
        if key in ("max_log_size", "backup_count", "max_queue_size"):
            return int(raw)
        return raw

    def set_override(self, key, value):
        self._overrides[key] = value
