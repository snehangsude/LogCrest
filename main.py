from src.log_decorator import log_decorator, DEBUG, INFO, WARNING, ERROR, CRITICAL
from helo import abce
from src.utils import initialize_logger

logger = initialize_logger(config_path="log_config.json")


@log_decorator(DEBUG)
def debug_function(a, b):
    logger.debug(f"Debug function called with arguments: {a}, {b}")
    return a + b

@log_decorator(INFO)
def info_function(a, b):
    logger.info(f"Info function called with arguments: {a}, {b}")
    return a - b

@log_decorator(WARNING)
def warning_function(a, b):
    logger.warning(f"Warning function called with arguments: {a}, {b}")
    return a * b

@log_decorator(ERROR)
def error_function(a, b):
    try:
        result = a / b
    except ZeroDivisionError as e:
        logger.error(f"Error function encountered an exception: {e}")
        return None
    return result

@log_decorator(CRITICAL)
def critical_function(a, b):
    logger.critical(f"Critical function called with arguments: {a}, {b}")
    return a ** b

if __name__ == "__main__":
    print(debug_function(10, 5))
    print(info_function(10, 5))
    print(warning_function(10, 5))
    print(error_function(10, 0)) 
    print(critical_function(2, 3))
    print(abce(10))
