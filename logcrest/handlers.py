import logging
from logging.handlers import RotatingFileHandler
from .interfaces import IHandler
from .config import LevelFilter, TraceFilter

class FileHandlerFactory(IHandler):
    """Creates a rotating file handler with specific filters"""
    def __init__(self, filename, level, filters, formatter, max_bytes, backup_count):
        self.filename = filename
        self.level = level
        self.filters = filters
        self.formatter = formatter
        self.max_bytes = max_bytes
        self.backup_count = backup_count

    def get_handler(self):
        # Create directory if missing
        self.filename.parent.mkdir(parents=True, exist_ok=True)
        
        handler = RotatingFileHandler(
            self.filename, 
            maxBytes=self.max_bytes, 
            backupCount=self.backup_count
        )
        handler.setLevel(self.level)
        for f in self.filters:
            handler.addFilter(f)
        handler.addFilter(TraceFilter())
        handler.setFormatter(self.formatter.get_formatter())
        return handler

class ConsoleHandlerFactory(IHandler):
    """Creates a standard stream handler for terminal output"""
    def __init__(self, level, formatter):
        self.level = level
        self.formatter = formatter

    def get_handler(self):
        handler = logging.StreamHandler()
        handler.setLevel(self.level)
        handler.addFilter(TraceFilter())
        handler.setFormatter(self.formatter.get_formatter())
        return handler
