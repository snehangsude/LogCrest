import logging
from pathlib import Path
import json

class LevelFilter(logging.Filter):
    """Restricts logs to a specific level range"""
    def __init__(self, min_level, max_level):
        super().__init__()
        self.min_level = min_level
        self.max_level = max_level

    def filter(self, record):   
        return self.min_level <= record.levelno <= self.max_level

class TraceFilter(logging.Filter):
    """Ensures trace_id exists and handles function name overrides"""
    def filter(self, record):
        if not hasattr(record, 'trace_id'):
            record.trace_id = "Global"
        
        # Pulls actual function name if provided by decorator
        if hasattr(record, 'actual_func_name'):
            record.funcName = record.actual_func_name
            
        return True

class ConfigManager:
    """Loads and validates log configuration from JSON"""
    def __init__(self, path="log_config.json"):
        self.path = Path(path)
        self.data = self._load()

    def _load(self):
        if not self.path.exists():
            return {}
        try:
            with open(self.path, 'r') as f:
                return json.load(f)
        except Exception:
            return {}

    def get(self, key, default):
        return self.data.get(key, default)
