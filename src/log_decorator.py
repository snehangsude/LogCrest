import logging
from functools import wraps
from src.utils import initialize_logger  # Import the helper function

DEBUG = logging.DEBUG
INFO = logging.INFO
WARNING = logging.WARNING
ERROR = logging.ERROR
CRITICAL = logging.CRITICAL

def log_decorator(level):
    """Log decorator to log function calls at a specified logging level."""
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger = initialize_logger()  # Get the global logger
            
            # Log function call entry with level-specific logging
            logger.log(level, f"Calling function '{func.__name__}' with args={args}, kwargs={kwargs}")
            
            try:
                result = func(*args, **kwargs)
                logger.log(level, f"Function '{func.__name__}' executed successfully with result={result}")
                return result
            except Exception as e:
                logger.log(level, f"Function '{func.__name__}' raised an exception: {e}")
                raise
        return wrapper
    return decorator
