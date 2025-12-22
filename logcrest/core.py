import logging
import queue
import atexit
from datetime import datetime
from pathlib import Path
from logging.handlers import QueueHandler, QueueListener
from .interfaces import ILoggerBuilder
from .config import ConfigManager, LevelFilter
from .formatters import JSONFormatter, ColorFormatter
from .handlers import FileHandlerFactory, ConsoleHandlerFactory

class AsyncLoggerBuilder(ILoggerBuilder):
    """Orchestrates the assembly of an asynchronous logger"""
    _listener = None

    def __init__(self, config_path="log_config.json"):
        self.config = ConfigManager(config_path)
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    def build(self):
        log_name = self.config.get("log_name", "app_logger")
        logger = logging.getLogger(log_name)
        logger.setLevel(logging.DEBUG)

        if not logger.handlers:
            # Setup background processing
            log_queue = queue.Queue(-1)
            handlers = self._prepare_handlers()
            
            # Start background listener
            AsyncLoggerBuilder._listener = QueueListener(log_queue, *handlers, respect_handler_level=True)
            AsyncLoggerBuilder._listener.start()
            
            # Link logger to queue
            logger.addHandler(QueueHandler(log_queue))
            atexit.register(AsyncLoggerBuilder._listener.stop)

        return logger

    def _prepare_handlers(self):
        """Assembles all required log handlers based on config"""
        base_dir = Path(self.config.get("base_log_dir", "logs"))
        max_bytes = int(self.config.get("max_log_size", 5242880))
        backup_count = int(self.config.get("backup_count", 3))
        use_json = self.config.get("use_json", True)

        # Choose formatter based on prefs
        file_formatter = JSONFormatter() if use_json else ColorFormatter()
        
        # Define handler list
        handlers = [
            FileHandlerFactory(
                base_dir / "success" / f"{self.timestamp}_success.log",
                logging.DEBUG,
                [LevelFilter(logging.DEBUG, logging.WARNING)],
                file_formatter, max_bytes, backup_count
            ).get_handler(),
            FileHandlerFactory(
                base_dir / "error" / f"{self.timestamp}_error.log",
                logging.ERROR,
                [LevelFilter(logging.ERROR, logging.CRITICAL)],
                file_formatter, max_bytes, backup_count
            ).get_handler(),
            ConsoleHandlerFactory(logging.INFO, ColorFormatter()).get_handler()
        ]
        return handlers
