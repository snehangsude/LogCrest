import asyncio
import logcrest
from logcrest import log_decorator, log_flow, DEBUG, log


# Configure programmatically — no log_config.json needed.
# Priority: configure() > env vars > log_config.json > defaults.
logcrest.configure(dir="logs", json=True, name="demo-svc", level="DEBUG")


# Basic sync usage — args suppressed by default (safe for sensitive data)
@log_decorator
def calculate_metrics(data_points):
    log.info(f"Processing {len(data_points)} points")
    return sum(data_points) / len(data_points)


# Explicit opt-in to arg logging for non-sensitive functions
@log_decorator(log_args=True, log_result=True)
def add(a, b):
    return a + b


# Sync nested tracing — both functions share the same Trace ID
@log_decorator
def validate_user(user_id):
    return user_id > 0

@log_decorator
def process_request(user_id):
    if validate_user(user_id):
        log.info("Request approved")


# Async support — decorator auto-detects coroutines
@log_decorator(DEBUG)
async def fetch_data(url):
    await asyncio.sleep(0.01)  # simulate I/O
    return {"status": "ok"}

@log_decorator
async def handle_request(url):
    log.info(f"Handling request for {url}")
    data = await fetch_data(url)  # shares the same Trace ID
    return data


# Flow tracking via decorator — builds a full timeline of nested calls
@log_decorator
def charge_card(amount):
    return {"status": "ok"}

@log_flow("checkout")
def process_checkout(order_id, amount):
    validate_user(1)
    charge_card(amount)
    return {"order": order_id}


# Flow tracking via context manager — for imperative blocks (NEW in v3.1)
def run_batch(items):
    with log_flow("batch-job"):
        for item in items:
            calculate_metrics(item)


# Async flow context manager (NEW in v3.1)
async def async_pipeline(url):
    async with log_flow("async-pipeline"):
        await fetch_data(url)
        await handle_request(url)


if __name__ == "__main__":
    print("--- Sync: basic ---")
    print(calculate_metrics([10, 20, 30]))

    print("\n--- Sync: with arg/result logging ---")
    print(add(3, 4))

    print("\n--- Sync: nested tracing ---")
    process_request(42)

    print("\n--- Async: nested tracing ---")
    print(asyncio.run(handle_request("https://example.com/api")))

    print("\n--- Flow: decorator (full timeline emitted to logs/flows/) ---")
    print(process_checkout("ORD-42", 99.99))

    print("\n--- Flow: sync context manager ---")
    run_batch([[1, 2, 3], [4, 5, 6]])

    print("\n--- Flow: async context manager ---")
    asyncio.run(async_pipeline("https://example.com/api"))

    # ── FastAPI / any ASGI framework ──────────────────────────────────────────
    # LogCrestMiddleware is pure stdlib ASGI (no Starlette/FastAPI import), so it
    # adds zero dependency weight and works with any ASGI app:
    #
    #     from fastapi import FastAPI
    #     import logcrest
    #
    #     app = FastAPI()
    #     logcrest.instrument(app)        # one line — every request becomes a flow
    #
    # WSGI frameworks (Flask, classic Django) are not ASGI — use @log_flow or
    # `with log_flow()` directly in those views instead.
