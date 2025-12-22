from abc import ABC, abstractmethod
import logging

class IFormatter(ABC):
    """Interface for log formatters"""
    @abstractmethod
    def get_formatter(self) -> logging.Formatter:
        pass

class IHandler(ABC):
    """Interface for log handlers"""
    @abstractmethod
    def get_handler(self) -> logging.Handler:
        pass

class ILoggerBuilder(ABC):
    """Interface for building loggers"""
    @abstractmethod
    def build(self) -> logging.Logger:
        pass
