import logging
import queue
import atexit
import warnings
from datetime import datetime
from pathlib import Path
from logging.handlers import QueueHandler, QueueListener
from .interfaces import ILoggerBuilder
from .config import ConfigManager, LevelFilter, TraceSnapshotFilter, FlowFilter, NoFlowFilter
from .formatters import JSONFormatter, ColorFormatter
from .handlers import FileHandlerFactory, ConsoleHandlerFactory

class AsyncLoggerBuilder(ILoggerBuilder):
    """Orchestrates the assembly of an asynchronous logger.

    _listener is an instance variable so two builders with different logger
    names each own their listener independently. The caller is responsible for
    keeping this builder alive (e.g. via utils._internal_builder) so the
    listener is not garbage-collected.
    """

    def __init__(self, config_path="log_config.json", overrides=None):
        self.config = ConfigManager(config_path, overrides=overrides)
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._listener = None

    def build(self):
        log_name = self.config.get("log_name", "app_logger")
        logger = logging.getLogger(log_name)
        logger.setLevel(logging.DEBUG)

        logger.setLevel(self._resolve_level())

        if not logger.handlers:
            # max_queue_size <= 0 (default) means unbounded — the historical
            # behaviour. A positive value bounds memory under sustained overload;
            # if the queue fills, the QueueHandler drops the record (and reports
            # via handleError) rather than letting memory grow without limit.
            queue_size = int(self.config.get("max_queue_size", -1))
            log_queue = queue.Queue(queue_size)
            handlers = self._prepare_handlers()

            self._listener = QueueListener(log_queue, *handlers, respect_handler_level=True)
            self._listener.start()

            queue_handler = QueueHandler(log_queue)
            queue_handler.addFilter(TraceSnapshotFilter())
            logger.addHandler(queue_handler)
            atexit.register(self._listener.stop)

        return logger

    def _resolve_level(self):
        """Resolve the configured log level to an int.

        Accepts level names ("DEBUG", "info"), numeric strings ("30"), and ints.
        An unrecognized name emits a UserWarning and falls back to DEBUG rather
        than silently picking the wrong level.
        """
        raw_level = self.config.get('log_level', 'DEBUG')
        if isinstance(raw_level, str):
            if raw_level.strip().lstrip('-').isdigit():
                return int(raw_level)
            level = getattr(logging, raw_level.upper(), None)
            if not isinstance(level, int):
                warnings.warn(
                    f"LogCrest: unknown log level '{raw_level}' — using DEBUG.",
                    UserWarning, stacklevel=3,
                )
                return logging.DEBUG
            return level
        return int(raw_level)

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
                [LevelFilter(logging.DEBUG, logging.WARNING), NoFlowFilter()],
                file_formatter, max_bytes, backup_count
            ).get_handler(),
            FileHandlerFactory(
                base_dir / "error" / f"{self.timestamp}_error.log",
                logging.ERROR,
                [LevelFilter(logging.ERROR, logging.CRITICAL), NoFlowFilter()],
                file_formatter, max_bytes, backup_count
            ).get_handler(),
            FileHandlerFactory(
                base_dir / "flows" / f"{self.timestamp}_flows.log",
                logging.DEBUG,
                [FlowFilter()],
                file_formatter, max_bytes, backup_count
            ).get_handler(),
            ConsoleHandlerFactory(logging.INFO, ColorFormatter()).get_handler()
        ]
        return handlers
