# LogCrest 🚀

A production-grade, asynchronous logging module for Python.

## Features
- **Smart Decorator**: Use `@log_decorator` for effortless logging.
- **Async Processing**: non-blocking log writes using background threads.
- **Trace IDs**: Automatic parent-child correlation for tracking requests.
- **JSON Formatting**: Structured logs ready for ELK/Datadog.
- **Beautiful Console**: Color-coded terminal output for developers.
- **SOLID Design**: Modular, extensible architecture.

## Installation
```bash
pip install logcrest
# or
uv pip install logcrest
```

## Quick Start
```python
from logcrest import log_decorator, log

@log_decorator
def my_function(x):
    log.info(f"Doing work with {x}")
    return x * 2

my_function(10)
```
