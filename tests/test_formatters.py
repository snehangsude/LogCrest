import logging
import json
from logcrest.formatters import JSONFormatter, ColorFormatter

def test_json_formatter():
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="test.py", lineno=10,
        msg="test message", args=None, exc_info=None, func="test_func"
    )
    record.trace_id = "12345"
    
    formatted = formatter.format(record)
    data = json.loads(formatted)
    
    assert data["message"] == "test message"
    assert data["level"] == "INFO"
    assert data["trace_id"] == "12345"
    assert data["function"] == "test_func"

def test_color_formatter():
    formatter = ColorFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="test.py", lineno=10,
        msg="hello", args=None, exc_info=None, func="test_func"
    )
    record.trace_id = "ABC"
    
    formatted = formatter.format(record)
    # Check if color reset code is in it or specific parts
    assert "\033[92m" in formatted # Blue/Green for INFO
    assert "[INFO]" in formatted
    assert "[ABC]" in formatted
