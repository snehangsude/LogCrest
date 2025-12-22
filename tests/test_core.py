import logging
import pytest
from logcrest.core import AsyncLoggerBuilder

def test_builder_initialization(tmp_path):
    # Setup a fake config to steer logs to tmp_path
    config_file = tmp_path / "config.json"
    import json
    config_file.write_text(json.dumps({
        "base_log_dir": str(tmp_path / "logs"),
        "log_name": "unique_test_builder"
    }))
    
    builder = AsyncLoggerBuilder(config_path=config_file)
    logger = builder.build()
    
    assert logger.name == "unique_test_builder"
    assert logger.level == logging.DEBUG
    # Should have a QueueHandler
    from logging.handlers import QueueHandler
    assert any(isinstance(h, QueueHandler) for h in logger.handlers)

def test_singleton_behavior():
    # Verify our utils.get_session_logger handles singleton
    from logcrest.utils import get_session_logger
    logger1 = get_session_logger()
    logger2 = get_session_logger()
    assert logger1 is logger2
