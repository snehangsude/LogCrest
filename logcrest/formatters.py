import logging
import json
from .interfaces import IFormatter

# Complete set of standard LogRecord attributes — extras beyond this are user-supplied context.
# Also excludes LogCrest internal fields already captured explicitly in the JSON envelope.
_STDLIB_ATTRS = frozenset({
    'args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename',
    'funcName', 'levelname', 'levelno', 'lineno', 'message', 'module',
    'msecs', 'msg', 'name', 'pathname', 'process', 'processName',
    'relativeCreated', 'stack_info', 'taskName', 'thread', 'threadName',
    'actual_func_name', 'trace_id',
})


class JSONFormatter(logging.Formatter, IFormatter):
    """Outputs logs as single-line JSON objects"""
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "trace_id": getattr(record, "trace_id", "Global"),
            "function": record.funcName,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key not in _STDLIB_ATTRS and not key.startswith("_"):
                log_data[key] = value

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # default=str: a non-serializable value in user-supplied `extra` is
        # coerced to its string form rather than raising — which in the
        # background log thread would otherwise silently drop the whole record.
        return json.dumps(log_data, default=str)

    def get_formatter(self):
        return self


class ColorFormatter(logging.Formatter, IFormatter):
    """Colorizes console output based on log level"""
    COLORS = {
        'DEBUG': '\033[94m',
        'INFO': '\033[92m',
        'WARNING': '\033[93m',
        'ERROR': '\033[91m',
        'CRITICAL': '\033[41m',
    }
    RESET = '\033[0m'

    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        trace = getattr(record, 'trace_id', 'Global')
        output = f"{color}[{record.levelname}]{self.RESET} [{trace}] {record.funcName}: {record.getMessage()}"
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            output += '\n' + record.exc_text
        if record.stack_info:
            output += '\n' + self.formatStack(record.stack_info)
        return output

    def get_formatter(self):
        return self
