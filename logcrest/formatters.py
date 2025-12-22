import logging
import json
from .interfaces import IFormatter

class JSONFormatter(logging.Formatter, IFormatter):
    """Outputs logs as single-line JSON objects"""
    def format(self, record):
        # Extract base fields
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "trace_id": getattr(record, "trace_id", "Global"),
            "function": record.funcName,
            "message": record.getMessage(),
        }
        
        # Add extra context attributes
        standard_extras = ["args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName", "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name", "pathname", "process", "processName", "relativeCreated", "stack_info", "thread", "threadName"]
        for key, value in record.__dict__.items():
            if key not in standard_extras and not key.startswith("_"):
                log_data[key] = value

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)

    def get_formatter(self):
        return self

class ColorFormatter(logging.Formatter, IFormatter):
    """Colorizes console output based on log level"""
    COLORS = {
        'DEBUG': '\033[94m',    # Blue
        'INFO': '\033[92m',     # Green
        'WARNING': '\033[93m',  # Yellow
        'ERROR': '\033[91m',    # Red
        'CRITICAL': '\033[41m', # Red Background
    }
    RESET = '\033[0m'

    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        trace = getattr(record, 'trace_id', 'Global')
        # Clean format for humans
        log_fmt = f"{color}[%(levelname)s]{self.RESET} [{trace}] %(funcName)s: %(message)s"
        return logging.Formatter(log_fmt).format(record)

    def get_formatter(self):
        return self
