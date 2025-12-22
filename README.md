# LogCrest

LogCrest is a high-performance, asynchronous logging framework for Python designed for production-grade tracing and structured logging with minimal overhead. It replaces standard boilerplate with a robust decorator-driven system that ensures execution timing, parent-child correlation (Trace IDs), and machine-readable output.

## Core Features

*   **Asynchronous Processing**: Logs are processed in a background thread using a non-blocking queue to ensure zero impact on application latency.
*   **Correlation Tracing**: Automatically propagates Trace IDs across nested function calls, allowing for end-to-end request tracking.
*   **Dual-Stream Formatting**: Outputs colorized, human-readable terminal logs for development and structured JSON for production log aggregators.
*   **Zero-Config Readiness**: Works out of the box with sensible defaults, while remaining fully customizable via JSON.
*   **SOLID Architecture**: Built on a modular foundation, making it easy to extend with custom handlers or formatters.

## Installation

```bash
pip install logcrest
```

## Practical Examples

### 1. Basic Usage
Decorate any function to automatically log its entry, exit, arguments, and execution time.

```python
from logcrest import log_decorator, log

@log_decorator
def calculate_metrics(data_points):
    log.info(f"Processing {len(data_points)} points")
    return sum(data_points) / len(data_points)

calculate_metrics([10, 20, 30])
```

### 2. Request Tracing (Nested Calls)
LogCrest maintains context across function boundaries. A single Trace ID will be shared across all nested decorated calls originating from a root function.

```python
@log_decorator
def validate_user(user_id):
    return user_id > 0

@log_decorator
def process_request(user_id):
    if validate_user(user_id):
        log.info("Request approved")

# Both functions will share the same Trace ID in the logs
process_request(42)
```

### 3. Automated Error Handling
LogCrest catches exceptions, logs the full traceback and execution time before the failure, and re-raises the exception for your application to handle.

```python
@log_decorator
def database_operation():
    raise ConnectionError("Lost connection to host")

try:
    database_operation()
except ConnectionError:
    pass # Error is already logged with full context
```

### 4. Custom Log Levels
Control the severity of your logs directly through the decorator.

```python
from logcrest import DEBUG, WARNING

@log_decorator(DEBUG)
def low_priority_task():
    log.debug("Internal step completed")

@log_decorator(WARNING)
def sensitive_operation():
    log.warning("System resources running low")
```

## Advanced Configuration

LogCrest looks for a `log_config.json` in your project root. If not found, it uses internal defaults.

```json
{
  "base_log_dir": "logs",
  "max_log_size": 5242880,
  "backup_count": 3,
  "use_json": true,
  "log_name": "app_system"
}
```

## Development and Testing

LogCrest is built for stability. To run the test suite:

```bash
pip install "logcrest[dev]"
pytest
```

LogCrest ensures your logs are as reliable as your code.
