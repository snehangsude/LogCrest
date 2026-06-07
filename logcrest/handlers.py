import os
import logging
from logging.handlers import RotatingFileHandler
from .interfaces import IHandler
from .config import LevelFilter, TraceFilter


def _secure_opener(path, flags):
    """Open with 0600 from creation. The mode is masked by umask, but 0600 has
    no group/other bits to begin with, so the result is 0600 under any umask."""
    return os.open(path, flags, 0o600)


class SecureRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that creates every file owner-only (0600).

    Overrides _open so the permission applies not just to the initial file but
    to every file created during rotation (the new base file and all backups).
    Using the opener creates the file 0600 atomically — no world-readable window
    between create and chmod. Log files may contain stack traces and other
    internal detail that must not be world- or group-readable.
    """
    def _open(self):
        return open(
            self.baseFilename,
            self.mode,
            encoding=self.encoding,
            errors=getattr(self, "errors", None),
            opener=_secure_opener,
        )


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
        self.filename.parent.mkdir(parents=True, exist_ok=True)

        handler = SecureRotatingFileHandler(
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
