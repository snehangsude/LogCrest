import os
import json
from pathlib import Path
from logcrest.config import ConfigManager

def test_config_defaults(tmp_path):
    # Test fallback when file doesn't exist
    config = ConfigManager(path=tmp_path / "nonexistent.json")
    assert config.get("log_name", "default") == "default"

def test_config_loading(tmp_path):
    # Test reading actual values
    config_file = tmp_path / "test_config.json"
    data = {"log_name": "test_logger", "max_log_size": 100}
    config_file.write_text(json.dumps(data))
    
    config = ConfigManager(path=config_file)
    assert config.get("log_name", "") == "test_logger"
    assert config.get("max_log_size", 0) == 100
