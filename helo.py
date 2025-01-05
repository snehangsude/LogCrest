from src.log_decorator import log_decorator, DEBUG, INFO, WARNING, ERROR, CRITICAL
from src.utils import initialize_logger

logger = initialize_logger(config_path="log_config.json")

@log_decorator(DEBUG)
def abce(x):
    logger.debug(f"Debug function called with argument: {x}")
    return x


