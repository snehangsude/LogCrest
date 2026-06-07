# LogCrest

LogCrest is a high-performance, asynchronous logging framework for Python designed for production-grade tracing and structured logging with minimal overhead. It replaces standard boilerplate with a decorator-driven system that automatically captures execution timing, parent-child correlation (Trace IDs), and machine-readable output — for both synchronous and asynchronous functions.

## Core Features

- **Async-native**: Works on both `def` and `async def` functions with identical behaviour and trace propagation across `await` chains.
- **Flow tracking**: `@log_flow` marks an entry point and automatically builds a full timeline — every nested decorated call, its timing, and final status — emitted as structured `flow_start` / `flow_end` records.
- **Secure by default**: Arguments and return values are never logged unless explicitly opted in, preventing accidental credential or PII exposure.
- **Asynchronous processing**: Logs are dispatched to a background thread via a non-blocking queue — zero impact on application latency.
- **Correlation tracing**: Automatically propagates Trace IDs across nested and awaited calls for end-to-end request tracking.
- **Dual-stream formatting**: Colorized human-readable output for development; structured JSON for production log aggregators.
- **Zero dependencies**: Pure stdlib — nothing to pin, nothing to conflict with. Even the FastAPI/ASGI middleware imports no third-party package.
- **Framework-agnostic ASGI**: The bundled middleware is pure ASGI — works with FastAPI, Starlette, Quart, or any ASGI app; safe to install alongside Flask, Django, or `requests`.
- **Zero-config readiness**: Sensible defaults out of the box, fully customisable in code via `logcrest.configure()` or a `log_config.json` file.
- **SOLID architecture**: Modular foundation — extend with custom handlers or formatters without touching core code.

## Installation

```bash
pip install logcrest
```

## Zero-line Setup

```python
from logcrest import log_decorator, log_flow, log

# That's it — LogCrest works with zero configuration.
```

To configure programmatically (no JSON file needed):

```python
import logcrest

logcrest.configure(
    dir="logs",
    json=True,
    name="checkout-svc",
    level="DEBUG",
)
```

To instrument a FastAPI app in one line:

```python
from fastapi import FastAPI
import logcrest

app = FastAPI()
logcrest.instrument(app)
```

## Quick Start

```python
from logcrest import log_decorator, log_flow, log

@log_flow("calculate")
def calculate_metrics(data_points):
    log.info(f"Processing {len(data_points)} points")
    return sum(data_points) / len(data_points)

calculate_metrics([10, 20, 30])
# Emits: flow_start → (user log) → flow_end with timeline and total_ms
```

## Practical Examples

### 1. Basic Decorator Usage

Decorate any function to automatically log its entry, exit, and execution time.

```python
from logcrest import log_decorator, log

@log_decorator
def process_order(order_id):
    log.info(f"Processing order {order_id}")
    return {"status": "confirmed"}

process_order("ORD-001")
```

### 2. Async Functions

The decorator detects `async def` automatically — no separate import or variant needed. Trace IDs propagate correctly across `await` chains.

```python
import asyncio
from logcrest import log_decorator, log

@log_decorator
async def fetch_user(user_id):
    # simulate DB call
    await asyncio.sleep(0.01)
    return {"id": user_id, "name": "Ada"}

@log_decorator
async def handle_request(user_id):
    log.info(f"Handling request for user {user_id}")
    user = await fetch_user(user_id)   # shares the same Trace ID
    return user

asyncio.run(handle_request(42))
```

Both `handle_request` and `fetch_user` will appear in logs under the same Trace ID, making the full call chain traceable in your log aggregator.

### 3. Request Tracing (Sync Nested Calls)

The same propagation works for synchronous nested calls.

```python
from logcrest import log_decorator

@log_decorator
def validate_user(user_id):
    return user_id > 0

@log_decorator
def process_request(user_id):
    if validate_user(user_id):
        log.info("Request approved")

process_request(42)
# Both functions share the same Trace ID in the logs
```

### 4. Security: Controlling What Gets Logged

**Arguments and return values are never logged by default.** This prevents accidental exposure of passwords, tokens, API keys, or PII. Opt in explicitly only for functions where it is safe to do so.

```python
from logcrest import log_decorator

# Safe — credentials are never written to the log files
@log_decorator
def authenticate(username, password):
    return check_credentials(username, password)

# Explicit opt-in for non-sensitive functions
@log_decorator(log_args=True, log_result=True)
def calculate_discount(price, rate):
    return price * (1 - rate)
```

This applies equally to async functions:

```python
@log_decorator(log_args=False)   # default, shown for clarity
async def refresh_token(user_id, token):
    ...
```

### 5. Custom Log Levels

Control the severity recorded by the decorator independently of `log.info()` calls inside the function.

```python
from logcrest import log_decorator, DEBUG, WARNING

@log_decorator(DEBUG)
def low_priority_task():
    log.debug("Internal step completed")

@log_decorator(WARNING)
def degraded_operation():
    log.warning("Falling back to secondary provider")

# Combine level with security options
@log_decorator(DEBUG, log_args=True)
async def cache_lookup(key):
    ...
```

### 6. Flow Tracking

`@log_flow` marks a function as the entry point of an observable business flow. It generates a unique flow ID, tracks every nested `@log_decorator` call in a timeline, and emits structured `flow_start` and `flow_end` records. Flows are written to a dedicated `logs/flows/` file, separate from per-function success and error logs.

```python
from logcrest import log_decorator, log_flow

@log_decorator
def validate_payment(amount):
    return amount > 0

@log_decorator
def charge_card(amount):
    # ... payment provider call
    return {"status": "ok"}

@log_flow("checkout")
def process_checkout(order_id, amount):
    validate_payment(amount)
    charge_card(amount)
    return {"order": order_id}

process_checkout("ORD-42", 99.99)
```

`flow_end` record (success):
```json
{
  "flow_id": "checkout-3a7e2b1f",
  "flow_type": "flow_end",
  "flow_status": "success",
  "total_ms": 12.4,
  "steps": 2,
  "timeline": [
    {"fn": "validate_payment", "ms": 0.1, "status": "ok"},
    {"fn": "charge_card",      "ms": 11.9, "status": "ok"}
  ]
}
```

On failure, `flow_end` includes `failed_at` (the function that raised), `step` (e.g. `"2/3"`), and `flow_error`:

```json
{
  "flow_status": "failed",
  "failed_at": "charge_card",
  "step": "2/3",
  "flow_error": "ConnectionError: gateway timeout"
}
```

**Flow ID options:**

```python
@log_flow                            # auto ID: "3a7e2b1f"
@log_flow("checkout")               # labelled: "checkout-3a7e2b1f"
@log_flow("order", log_args=True)   # accepts all @log_decorator params
@log_flow(label_from="request_id")  # dynamic label from named kwarg
@log_flow(label_from=0)             # dynamic label from first positional arg
```

Works identically on `async def` functions. Nested `@log_flow` calls inside an active flow degrade gracefully — they emit a `UserWarning`, appear in the outer timeline, and do not start a new flow context.

### 7. `log_flow` as a Context Manager

For imperative code where a decorator doesn't fit, use `log_flow` as a sync or async context manager. The API is identical to the decorator — same flow ID, same timeline tracking, same `flow_start`/`flow_end` records.

```python
from logcrest import log_flow, log_decorator

@log_decorator
def validate_payment(amount):
    return amount > 0

@log_decorator
def charge_card(amount):
    return {"status": "ok"}

# Sync block — flow tracked automatically
with log_flow("checkout"):
    validate_payment(99.99)
    charge_card(99.99)

# Async block — same API, async-native
async def process_order(amount):
    async with log_flow("async-checkout"):
        await validate_payment_async(amount)
        await charge_card_async(amount)
```

Both forms emit `flow_start` on entry and `flow_end` (success or failed) on exit. Exceptions are not suppressed. The context manager degrades gracefully when nested inside an active flow, exactly like the decorator. This is also the recommended way to add flow tracking inside **WSGI** views (Flask, classic Django) where the ASGI middleware does not apply.

### 8. FastAPI / ASGI Integration

LogCrest ships a **pure-stdlib ASGI** middleware. It imports no third-party package — not even Starlette or FastAPI — so it adds zero weight to LogCrest's dependency footprint and works with any ASGI framework (FastAPI, Starlette, Quart, …). Every HTTP request is automatically wrapped in a flow context; route handlers and any `@log_decorator` functions they call appear directly in the request timeline with no extra code.

```python
from fastapi import FastAPI
import logcrest

app = FastAPI()
logcrest.instrument(app)   # one line — every request becomes a flow

@logcrest.log_decorator
async def fetch_order(order_id: str):
    # ... DB call
    return {"id": order_id}

@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    return await fetch_order(order_id)
```

`logcrest.instrument(app)` is the recommended entry point. The middleware class can also be added explicitly — both import paths point to the same pure-ASGI class:

```python
from logcrest.integrations.asgi import LogCrestMiddleware      # framework-agnostic path
# or, equivalently:
from logcrest.integrations.fastapi import LogCrestMiddleware

app.add_middleware(LogCrestMiddleware)        # FastAPI / Starlette
app = LogCrestMiddleware(app)                 # any raw ASGI app
```

**What you get automatically:**

- `X-Flow-ID` response header on every request — pass it to clients for end-to-end tracing.
- `flow_start` record on entry, `flow_end` record on exit (status `success` or `failed`).
- Every `@log_decorator` function called inside the handler appears as a timeline step in `flow_end`.
- `flow_id_context` and `trace_context` set for the lifetime of the request — readable anywhere inside the handler or any async function it awaits.
- Concurrent `asyncio.gather()` steps each appear in the timeline independently.
- Unhandled handler exceptions emit `flow_end` with `flow_status: "failed"` and `failed_at`, then re-raise — your existing error handlers are not affected.

**X-Request-ID support:**

If the client sends an `X-Request-ID` header, its value becomes the flow label prefix:

```
X-Request-ID: checkout-session-7f3a
→ X-Flow-ID: checkout-session-7f3a-4b8c1e2d
```

**Nested `@log_flow` inside a handler** degrades gracefully — the handler appears as a timeline step in the middleware-owned flow and emits a `UserWarning`. No duplicate `flow_start`/`flow_end` records are emitted.

**A note on frameworks:** the middleware is ASGI, so it attaches to ASGI apps (FastAPI, Starlette, Quart). **WSGI** frameworks — Flask and classic Django-WSGI — are a different protocol; an ASGI middleware cannot wrap them. There is no conflict from having LogCrest installed alongside them (LogCrest imports nothing global), and `@log_decorator` / `with log_flow()` work in those views directly. Likewise, client libraries such as `requests` are entirely unaffected.

**Install:**

```bash
pip install logcrest          # core — zero dependencies
pip install fastapi uvicorn   # only if you serve an ASGI app
```

### 9. Automated Error Handling

LogCrest catches exceptions, logs the full traceback and elapsed time, then re-raises so your application can handle it normally.

```python
from logcrest import log_decorator

@log_decorator
async def database_write(record):
    raise ConnectionError("Lost connection to host")

try:
    await database_write(record)
except ConnectionError:
    pass  # Already logged with trace ID, function name, and elapsed time
```

## Advanced Configuration

LogCrest looks for `log_config.json` in the current working directory at logger initialisation time. If not found, internal defaults are used. If the file exists but is malformed or unreadable, a `warnings.warn()` is emitted and defaults are used — it will never silently misconfigure.

```json
{
  "base_log_dir": "logs",
  "max_log_size": 5242880,
  "backup_count": 3,
  "use_json": true,
  "log_name": "app_system"
}
```

| Key | Default | Description |
|---|---|---|
| `base_log_dir` | `"logs"` | Root directory for log files |
| `max_log_size` | `5242880` | Max bytes per log file before rotation (5 MB) |
| `backup_count` | `3` | Number of rotated files to retain |
| `use_json` | `true` | JSON formatter for files; `false` uses colour text |
| `log_name` | `"app_logger"` | Logger name (useful when running multiple services) |

### Log file layout

```
logs/
  success/  — DEBUG through WARNING (timestamped, rotating) — no flow records
  error/    — ERROR and CRITICAL (timestamped, rotating)    — no flow records
  flows/    — flow_start and flow_end records only
```

Flow records are routed exclusively to `flows/` and excluded from `success/` and `error/`, keeping per-function noise separate from high-level flow summaries. All log files — including rotated backups — are created with `0600` permissions (owner read/write only) on POSIX systems. Console output is always colorized regardless of `use_json`.

## Configuration API Reference

### `logcrest.configure()`

```python
logcrest.configure(
    dir="logs",          # base directory for log files
    json=True,           # JSON-formatted files; False for colour text
    name="my-service",   # logger name
    level="DEBUG",       # minimum log level — string or int
    max_size=5_242_880,  # max bytes per file before rotation
    backup_count=3,      # rotated files to keep
    queue_size=0,        # async queue cap; <= 0 means unbounded
)
```

All parameters are optional. `configure()` can be called before the first log statement (zero overhead — logger is built lazily with the new settings) or after (triggers a clean rebuild — old listener stopped, handlers cleared, no duplicate output).

**Priority:** `configure()` kwargs **>** environment variables **>** `log_config.json` **>** built-in defaults.

| Parameter | Type | Default | Config key |
|---|---|---|---|
| `dir` | `str` | `"logs"` | `base_log_dir` |
| `json` | `bool` | `True` | `use_json` |
| `name` | `str` | `"app_logger"` | `log_name` |
| `level` | `str \| int` | `"DEBUG"` | `log_level` |
| `max_size` | `int` | `5242880` | `max_log_size` |
| `backup_count` | `int` | `3` | `backup_count` |
| `queue_size` | `int` | `0` (unbounded) | `max_queue_size` |

A non-numeric `level` string that isn't a recognized level name emits a `UserWarning` and falls back to `DEBUG`; numeric strings (e.g. `"30"`) are coerced to the matching level.

Environment variable equivalents: `LOGCREST_DIR`, `LOGCREST_JSON`, `LOGCREST_NAME`, `LOGCREST_LEVEL`, `LOGCREST_MAX_SIZE`, `LOGCREST_BACKUP_COUNT`, `LOGCREST_QUEUE_SIZE`.

---

### `logcrest.instrument(app)`

```python
import logcrest
logcrest.instrument(app)                        # default settings
logcrest.instrument(app, level=logging.DEBUG)   # custom level
```

Attaches `LogCrestMiddleware` to a FastAPI or Starlette app without requiring any middleware import. Returns `app` so the call can be chained.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `app` | `ASGIApp` | — | FastAPI or Starlette application |
| `level` | `int` | `INFO` | Log level for `flow_start` and successful `flow_end` records |

---

## Decorator API Reference

### `@log_decorator`

```
@log_decorator
@log_decorator(level)
@log_decorator(level, log_args=True)
@log_decorator(level, log_result=True)
@log_decorator(log_args=True, log_result=True)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `level` | `int` | `INFO` | Log level for entry/exit messages. Use `DEBUG`, `WARNING`, etc. |
| `log_args` | `bool` | `False` | Log function arguments verbatim. Only enable for non-sensitive functions. |
| `log_result` | `bool` | `False` | Log return value verbatim. Only enable for non-sensitive functions. |

Works on both `def` and `async def` — no separate async variant needed. When called inside an active `@log_flow`, each call automatically appears in the flow timeline.

### `@log_flow` / `with log_flow()` / `async with log_flow()`

```
# Decorator forms
@log_flow
@log_flow("label")
@log_flow("label", log_args=True)
@log_flow("label", level=DEBUG)
@log_flow(label_from="kwarg_name")
@log_flow(label_from=0)

# Context manager forms (same parameters)
with log_flow("label"):
    ...

async with log_flow("label"):
    ...
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `label` | `str` | — | Static label prepended to the flow ID: `"checkout-3a7e2b1f"`. |
| `label_from` | `str \| int` | `None` | Extract label dynamically from a kwarg name or positional arg index at call time. Falls back to bare hex ID if the key/index is missing. |
| `level` | `int` | `INFO` | Log level for `flow_start` and `flow_end` records. Failures always emit at `ERROR`. |
| `log_args` | `bool` | `False` | Include function arguments in the `flow_start` message. |
| `log_result` | `bool` | `False` | Reserved for future use. |

Flow records written to `logs/flows/`. Nested `@log_flow` inside an active flow degrades to `@log_decorator` and emits a `UserWarning`.

## Development and Testing

```bash
pip install "logcrest[dev]"
pytest
```

## Changelog

### v3.0.0

Major release. Adds flow tracking, a pure-stdlib ASGI integration, a programmatic
configuration API, and a round of security/robustness hardening.

**New features**

- `@log_flow` decorator — marks a function as a flow entry point. Generates a unique flow ID (`label-{hex8}` or `{hex8}`), tracks every nested `@log_decorator` call in a timeline ContextVar, and emits structured `flow_start` / `flow_end` records. Supports `label_from` for dynamic IDs extracted from kwargs or positional args. Works on `def` and `async def`. Nested `@log_flow` inside an active flow degrades gracefully with a `UserWarning`.
- `log_flow` as a context manager — `with log_flow("label"):` and `async with log_flow("label"):` work identically to the decorator form. Emits `flow_start` / `flow_end`, tracks nested `@log_decorator` calls in the timeline, degrades gracefully inside an active flow, and propagates exceptions unchanged. The recommended way to add flow tracking inside WSGI views (Flask, classic Django).
- `logs/flows/` handler — `flow_start` and `flow_end` records are routed to a dedicated rotating file under `logs/flows/`. Existing `success/` and `error/` handlers exclude flow records via `NoFlowFilter`, keeping per-function and flow-level logs separate.
- `flow_id_context` and `flow_stack_context` — new `ContextVar`s exposed from `logcrest.utils` for reading the active flow ID or inspecting the timeline from user code.
- `logcrest.configure()` — programmatic configuration API. Set log directory, name, level, JSON mode, rotation settings, and queue size in code. Takes priority over env vars and `log_config.json`. Works before or after the logger is first built (triggers a clean rebuild with no duplicate output).
- `logcrest.instrument(app)` — one-line ASGI middleware attachment. `instrument(app)` is equivalent to `app.add_middleware(LogCrestMiddleware)`. Returns the app for optional chaining.
- `LogCrestMiddleware` — pure-stdlib ASGI middleware (FastAPI / Starlette / Quart / any ASGI app). Every HTTP request is automatically wrapped in a flow: `X-Flow-ID` header injected, `flow_start`/`flow_end` emitted, `@log_decorator` calls inside route handlers appear in the request timeline, and concurrent `asyncio.gather()` steps are tracked independently. Available from `logcrest.integrations.asgi` (framework-agnostic) or `logcrest.integrations.fastapi` (same class).

**Security**

- **Log file permissions survive rotation.** Files are created `0600` (owner-only) atomically via `SecureRotatingFileHandler`'s `open()` opener hook — not just the initial file but every file produced during rotation (new base file and all backups), on POSIX systems. The earlier approach chmod'd only once at creation, leaving rotated files at the process umask (commonly `0644`, world-readable) in steady-state production. Covered by `tests/test_handler_permissions.py`.
- **Log-forging defense in the ASGI middleware.** The request path is escaped (`\r`/`\n`) before being written into flow records, so an attacker-controlled URL path cannot inject forged log lines into the text-formatted log. (The JSON formatter was already immune.)
- **Secure by default** — `log_args` / `log_result` remain `False` (see v2.0.0); arguments and return values are never logged unless explicitly opted in.

**Robustness**

- `JSONFormatter` no longer drops records on non-serializable `extra` values — `json.dumps(..., default=str)` coerces them to a string instead of raising in the background log thread (which previously discarded the whole record).
- Bounded async queue option — `configure(queue_size=N)` / `LOGCREST_QUEUE_SIZE` caps the in-memory log queue to guard against unbounded growth under sustained overload. Default remains unbounded (`<= 0`), preserving prior behaviour.
- Robust log-level resolution — an unrecognized level string emits a `UserWarning` and falls back to `DEBUG`; numeric-string levels (e.g. `"30"` from an env var) are coerced correctly.

**Bug fixes**

- `trace_id` missing from `log.*()` calls inside `@log_decorator` — `TraceFilter` was never reading from `contextvars`. Fixed with `TraceSnapshotFilter` on the `QueueHandler` (captures trace ID in the calling thread before the record enters the async queue) and a corrected `TraceFilter` fallback on downstream handlers.
- `_listener` class-variable bug — two `AsyncLoggerBuilder` instances sharing a logger name caused the second `build()` to silently overwrite the first's `QueueListener`. Fixed by moving `_listener` to an instance variable; builder reference kept alive in `utils.py`.
- Unknown config keys silently ignored — typos in `log_config.json` now emit a `UserWarning` per unknown key at load time.

**Dependency / footprint**

- LogCrest remains **zero-dependency**, and that now includes the web integration: `LogCrestMiddleware` imports no third-party package (no Starlette, no FastAPI). It works with any ASGI framework and never conflicts with Flask, Django, or `requests`. `fastapi` and `httpx` are dev-only (test) dependencies.

**New configuration**

- Environment variables override `log_config.json` with correct type coercion: `LOGCREST_NAME`, `LOGCREST_DIR`, `LOGCREST_JSON`, `LOGCREST_LEVEL`, `LOGCREST_MAX_SIZE`, `LOGCREST_BACKUP_COUNT`, `LOGCREST_QUEUE_SIZE`.

### v2.0.0

**Breaking changes**

- `log_args` now defaults to `False`. Arguments are no longer logged unless explicitly opted in with `@log_decorator(log_args=True)`. This prevents accidental credential and PII exposure. If you relied on argument logging, add `log_args=True` to affected decorators.
- `log_result` parameter added, also defaulting to `False`. Return values were previously always logged on exit.

**New features**

- Full `async def` support. The decorator auto-detects coroutine functions using `inspect.iscoroutinefunction()` and wraps them with an `async` wrapper. Trace ID propagation works correctly across `await` chains via `contextvars`.
- `log_result` parameter for explicit opt-in to return value logging.

**Security fixes**

- Arguments and return values are suppressed by default (see breaking changes above).
- `JSONFormatter` now uses a complete `frozenset` of standard `LogRecord` attributes to prevent internal fields from leaking into structured log output.
- Log files are created with `0600` permissions (owner read/write only) instead of the OS default `0644`.
- `ConfigManager` now emits a `warnings.warn()` when `log_config.json` exists but cannot be parsed or read, rather than silently falling back to defaults.

**Performance**

- `ColorFormatter` no longer allocates a new `logging.Formatter` instance on every log call. Format is now built directly from the record, eliminating per-call object allocation.

### v1.0.1

- Initial public release.
- Async queue via `QueueHandler`/`QueueListener`.
- Trace propagation with `contextvars`.
- Split success/error file routing with rotating file handlers.
- JSON and colour formatters.
- Zero-config defaults with optional `log_config.json`.
