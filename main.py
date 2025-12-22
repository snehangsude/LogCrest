from logcrest import log_decorator, DEBUG, INFO, log

@log_decorator
def hello_world(name):
    log.info(f"Inside hello_world, saying hi to {name}")
    return f"Hello, {name}!"

@log_decorator(DEBUG)
def child_function(v):
    return v * 2

@log_decorator(INFO)
def parent_function(x):
    log.info(f"Parent function doing work with {x}")
    val = child_function(x)
    return val + 10

if __name__ == "__main__":
    print("--- Root Call ---")
    print(hello_world("Portfolio User"))
    
    print("\n--- Nested Tracing Call ---")
    print(parent_function(5))
