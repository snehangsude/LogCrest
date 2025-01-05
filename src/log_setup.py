import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime, timedelta
import json
import os

class LevelFilter(logging.Filter):
    """Filter logs based on the level range."""
    
    def __init__(self, min_level, max_level):
        super().__init__()
        self.min_level = min_level
        self.max_level = max_level

    def filter(self, record):   
        return self.min_level <= record.levelno <= self.max_level


class LogSetup:
    """Sets up loggers with success and error handlers, including log rotation."""
    
    _cached_config = None
    _config_last_loaded = None

    def __init__(self, base_log_dir="logs", log_name="app_logger", max_log_size=5 * 1024 * 1024, backup_count=3, config_path="log_config.json", cache_expiry_time=60):
        self.base_log_dir = Path(base_log_dir)
        self.log_name = log_name
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.max_log_size = max_log_size  
        self.backup_count = backup_count  
        self.config_path = Path(config_path)
        self.cache_expiry_time = cache_expiry_time 
        
        # config is not cached or expired, load it from the file
        if LogSetup._cached_config is None or self._is_cache_expired():
            LogSetup._cached_config = self._load_config()
            LogSetup._config_last_loaded = datetime.now()

    def _is_cache_expired(self):
        """Check if the cached configuration has expired."""
        if LogSetup._config_last_loaded is None:
            return True
        # If the cache is older than the specified expiry time, reload the config
        return (datetime.now() - LogSetup._config_last_loaded) > timedelta(seconds=self.cache_expiry_time)

    def _load_config(self):
        """Load configuration from the log_config.json file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
        
        # Check if the configuration file has changed since the last load
        file_mod_time = datetime.fromtimestamp(os.path.getmtime(self.config_path))
        if LogSetup._config_last_loaded and file_mod_time > LogSetup._config_last_loaded:
            print("Reloading configuration due to file change...")

        with open(self.config_path, 'r') as f:
            config = json.load(f)
        
        return config

    def get_logger(self):
        """Create and return a configured logger."""
        logger = logging.getLogger(self.log_name)
        logger.setLevel(logging.DEBUG)
        
        if not logger.hasHandlers():  # Prevent duplicate handlers
            self._add_success_handler(logger)
            self._add_error_handler(logger)
        
        return logger
    
    def _add_success_handler(self, logger):
        """Add a success log handler for INFO and DEBUG levels with log rotation."""
        success_dir = self.base_log_dir / "success"
        success_dir.mkdir(parents=True, exist_ok=True)
        success_log_file = success_dir / f"{self.timestamp}_{self.log_name}.log"
        
        success_handler = RotatingFileHandler(success_log_file, maxBytes=self.max_log_size, backupCount=self.backup_count)
        success_handler.setLevel(logging.DEBUG)
        success_handler.addFilter(LevelFilter(logging.DEBUG, logging.WARNING))
        success_handler.setFormatter(self._get_formatter())
        logger.addHandler(success_handler)
    
    def _add_error_handler(self, logger):
        """Add an error log handler for ERROR and CRITICAL levels with log rotation."""
        error_dir = self.base_log_dir / "error"
        error_dir.mkdir(parents=True, exist_ok=True)
        error_log_file = error_dir / f"{self.timestamp}_{self.log_name}.log"
        
        error_handler = RotatingFileHandler(error_log_file, maxBytes=self.max_log_size, backupCount=self.backup_count)
        error_handler.setLevel(logging.ERROR)
        error_handler.addFilter(LevelFilter(logging.ERROR, logging.CRITICAL))
        error_handler.setFormatter(self._get_formatter())
        logger.addHandler(error_handler)
    
    def _get_formatter(self):
        """Return a standard formatter for log messages."""
        return logging.Formatter('%(asctime)s - %(module)s - %(levelname)s - %(message)s')
