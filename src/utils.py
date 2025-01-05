import logging
from src.log_setup import LogSetup

# Global logger variable
logger = None

def initialize_logger(config_path="log_config.json"):
    """Initialize the global logger if it hasn't been initialized yet."""
    global logger
    if logger is None:
        try:
            logger_setup = LogSetup(config_path=config_path)
            logger = logger_setup.get_logger()
        except (FileNotFoundError, ValueError) as e:
            raise RuntimeError(f"Failed to initialize logger: {e}")
    return logger
