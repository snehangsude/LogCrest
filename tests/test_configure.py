"""
TDD tests for logcrest.configure() — programmatic configuration API.

Goal: configure(dir=..., json=..., name=..., level=...) lets users configure
LogCrest entirely in code, with higher priority than log_config.json and env vars.

Implementation targets:
  logcrest/utils.py   — _code_config dict, configure(), _rebuild()
  logcrest/config.py  — ConfigManager.__init__ accepts overrides kwarg
  logcrest/core.py    — AsyncLoggerBuilder passes overrides to ConfigManager
  logcrest/__init__.py — expose configure
"""
import logging
import os
import pytest


# ── Fixture: reset global LogCrest state between tests ───────────────────────

@pytest.fixture(autouse=True)
def reset_logcrest():
    """Ensure each test starts and ends with a clean LogCrest global state."""
    import logcrest.utils as _u
    import importlib

    saved_code_config = dict(getattr(_u, '_code_config', {}))
    saved_logger = _u._internal_logger
    saved_builder = _u._internal_builder

    yield

    # Stop any listener started during the test
    current_builder = _u._internal_builder
    if current_builder is not None and current_builder is not saved_builder:
        if current_builder._listener is not None:
            try:
                current_builder._listener.stop()
            except Exception:
                pass
        log_name = current_builder.config.get('log_name', 'app_logger')
        logging.getLogger(log_name).handlers.clear()

    # Restore globals
    if hasattr(_u, '_code_config'):
        _u._code_config.clear()
        _u._code_config.update(saved_code_config)
    _u._internal_logger = saved_logger
    _u._internal_builder = saved_builder


# ── Group 1: API surface ──────────────────────────────────────────────────────

class TestConfigureImport:
    def test_configure_importable_from_logcrest(self):
        from logcrest import configure
        assert callable(configure)

    def test_configure_no_args_does_not_raise(self):
        from logcrest import configure
        configure()  # should be a no-op

    def test_configure_returns_none(self):
        from logcrest import configure
        result = configure(name="return-test")
        assert result is None


# ── Group 2: name parameter ───────────────────────────────────────────────────

class TestConfigureName:
    def test_configure_name_sets_logger_name(self, tmp_path):
        from logcrest import configure
        import logcrest.utils as _u
        configure(name="my-service", dir=str(tmp_path))
        logger = _u.get_session_logger()
        assert logger.name == "my-service"

    def test_configure_name_different_from_default(self, tmp_path):
        from logcrest import configure
        import logcrest.utils as _u
        configure(name="custom-app", dir=str(tmp_path))
        logger = _u.get_session_logger()
        assert logger.name != "app_logger"

    def test_configure_before_first_log_takes_effect(self, tmp_path):
        """configure() called before any log access must still apply."""
        import logcrest.utils as _u
        assert _u._internal_logger is None, "Logger must not be pre-built for this test"
        from logcrest import configure
        configure(name="pre-build-test", dir=str(tmp_path))
        logger = _u.get_session_logger()
        assert logger.name == "pre-build-test"


# ── Group 3: dir parameter ────────────────────────────────────────────────────

class TestConfigureDir:
    def test_configure_dir_stored_in_config(self, tmp_path):
        from logcrest import configure
        import logcrest.utils as _u
        target = str(tmp_path / "my_logs")
        configure(dir=target, name="dir-test")
        _u.get_session_logger()
        assert _u._internal_builder.config.get('base_log_dir', None) == target

    def test_configure_dir_used_for_log_files(self, tmp_path):
        """Log files must appear under the configured dir after a log call."""
        from logcrest import configure
        import logcrest.utils as _u
        import time
        log_dir = tmp_path / "custom_dir"
        configure(dir=str(log_dir), name="dir-files-test")
        logger = _u.get_session_logger()
        logger.info("dir test")
        time.sleep(0.15)
        assert log_dir.exists()


# ── Group 4: json parameter ───────────────────────────────────────────────────

class TestConfigureJson:
    def test_configure_json_true_stored_in_config(self, tmp_path):
        from logcrest import configure
        import logcrest.utils as _u
        configure(json=True, name="json-true", dir=str(tmp_path))
        _u.get_session_logger()
        assert _u._internal_builder.config.get('use_json', None) is True

    def test_configure_json_false_stored_in_config(self, tmp_path):
        from logcrest import configure
        import logcrest.utils as _u
        configure(json=False, name="json-false", dir=str(tmp_path))
        _u.get_session_logger()
        assert _u._internal_builder.config.get('use_json', None) is False


# ── Group 5: level parameter ──────────────────────────────────────────────────

class TestConfigureLevel:
    def test_configure_level_string_debug(self, tmp_path):
        from logcrest import configure
        import logcrest.utils as _u
        configure(level="DEBUG", name="lvl-debug", dir=str(tmp_path))
        logger = _u.get_session_logger()
        assert logger.level == logging.DEBUG

    def test_configure_level_string_warning(self, tmp_path):
        from logcrest import configure
        import logcrest.utils as _u
        configure(level="WARNING", name="lvl-warning", dir=str(tmp_path))
        logger = _u.get_session_logger()
        assert logger.level == logging.WARNING

    def test_configure_level_int(self, tmp_path):
        from logcrest import configure
        import logcrest.utils as _u
        configure(level=logging.ERROR, name="lvl-int", dir=str(tmp_path))
        logger = _u.get_session_logger()
        assert logger.level == logging.ERROR

    def test_configure_level_string_case_insensitive(self, tmp_path):
        from logcrest import configure
        import logcrest.utils as _u
        configure(level="info", name="lvl-lower", dir=str(tmp_path))
        logger = _u.get_session_logger()
        assert logger.level == logging.INFO


# ── Group 6: max_size and backup_count ───────────────────────────────────────

class TestConfigureSizeOptions:
    def test_configure_max_size_stored_in_config(self, tmp_path):
        from logcrest import configure
        import logcrest.utils as _u
        configure(max_size=1_000_000, name="maxsize-test", dir=str(tmp_path))
        _u.get_session_logger()
        assert int(_u._internal_builder.config.get('max_log_size', 0)) == 1_000_000

    def test_configure_backup_count_stored_in_config(self, tmp_path):
        from logcrest import configure
        import logcrest.utils as _u
        configure(backup_count=7, name="backup-test", dir=str(tmp_path))
        _u.get_session_logger()
        assert int(_u._internal_builder.config.get('backup_count', 0)) == 7


# ── Group 7: priority over JSON file ─────────────────────────────────────────

class TestConfigurePriority:
    def test_configure_overrides_json_file(self, tmp_path):
        """configure() kwargs must win over log_config.json values."""
        import json as _json
        from logcrest import configure
        import logcrest.utils as _u

        # Write a JSON file with a different name
        cfg = tmp_path / "log_config.json"
        cfg.write_text(_json.dumps({"log_name": "from-json-file"}))

        configure(name="from-configure", dir=str(tmp_path))
        logger = _u.get_session_logger()
        assert logger.name == "from-configure"

    def test_configure_overrides_env_var(self, tmp_path, monkeypatch):
        """configure() kwargs must win over LOGCREST_NAME env var."""
        monkeypatch.setenv("LOGCREST_NAME", "from-env-var")
        from logcrest import configure
        import logcrest.utils as _u

        configure(name="from-configure", dir=str(tmp_path))
        logger = _u.get_session_logger()
        assert logger.name == "from-configure"

    def test_unconfigured_key_still_reads_env_var(self, tmp_path, monkeypatch):
        """Keys NOT passed to configure() still fall back to env vars."""
        monkeypatch.setenv("LOGCREST_NAME", "env-name-fallback")
        from logcrest import configure
        import logcrest.utils as _u

        # configure only sets dir, not name
        configure(dir=str(tmp_path))
        logger = _u.get_session_logger()
        assert logger.name == "env-name-fallback"


# ── Group 8: rebuild after first use ─────────────────────────────────────────

class TestConfigureRebuild:
    def test_configure_after_first_log_rebuilds_logger(self, tmp_path):
        """Calling configure() after logger is already built must cause a rebuild."""
        from logcrest import configure
        import logcrest.utils as _u

        # Build with default name
        configure(name="first-build", dir=str(tmp_path))
        first = _u.get_session_logger()
        assert first.name == "first-build"

        # Reconfigure with a new name
        configure(name="second-build", dir=str(tmp_path))
        second = _u.get_session_logger()
        assert second.name == "second-build"

    def test_configure_rebuild_resets_old_logger_handlers(self, tmp_path):
        """After rebuild, the old logger must have no handlers (avoid duplicate output)."""
        from logcrest import configure
        import logcrest.utils as _u

        configure(name="old-logger", dir=str(tmp_path))
        _u.get_session_logger()

        configure(name="new-logger", dir=str(tmp_path))
        _u.get_session_logger()

        old_logger = logging.getLogger("old-logger")
        assert len(old_logger.handlers) == 0


# ── Group 9: queue size (#3 — bound the async queue) ─────────────────────────

class TestConfigureQueueSize:
    def _queue_handler(self, logger):
        from logging.handlers import QueueHandler
        return next(h for h in logger.handlers if isinstance(h, QueueHandler))

    def test_default_queue_is_unbounded(self, tmp_path):
        from logcrest import configure
        import logcrest.utils as _u
        configure(name="q-default", dir=str(tmp_path))
        logger = _u.get_session_logger()
        qh = self._queue_handler(logger)
        # Queue(maxsize<=0) is unbounded; maxsize attribute reflects the arg.
        assert qh.queue.maxsize <= 0

    def test_configure_queue_size_bounds_the_queue(self, tmp_path):
        from logcrest import configure
        import logcrest.utils as _u
        configure(name="q-bounded", dir=str(tmp_path), queue_size=128)
        logger = _u.get_session_logger()
        qh = self._queue_handler(logger)
        assert qh.queue.maxsize == 128

    def test_queue_size_stored_in_config(self, tmp_path):
        from logcrest import configure
        import logcrest.utils as _u
        configure(name="q-config", dir=str(tmp_path), queue_size=64)
        _u.get_session_logger()
        assert int(_u._internal_builder.config.get('max_queue_size', -1)) == 64


# ── Group 10: invalid / numeric level handling (#4) ──────────────────────────

class TestConfigureLevelEdgeCases:
    def test_invalid_level_string_warns(self, tmp_path):
        import warnings
        from logcrest import configure
        import logcrest.utils as _u
        configure(level="NOPE", name="lvl-bad", dir=str(tmp_path))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _u.get_session_logger()
        assert any("unknown log level" in str(x.message).lower() for x in w), (
            "An unrecognized level string must emit a UserWarning"
        )

    def test_invalid_level_falls_back_to_debug(self, tmp_path):
        from logcrest import configure
        import logcrest.utils as _u
        import warnings
        configure(level="NOPE", name="lvl-bad-fallback", dir=str(tmp_path))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            logger = _u.get_session_logger()
        assert logger.level == logging.DEBUG

    def test_numeric_string_level_is_coerced(self, tmp_path):
        """A numeric-string level (e.g. from an env var) must be honoured, not dropped."""
        from logcrest import configure
        import logcrest.utils as _u
        configure(level="30", name="lvl-numeric", dir=str(tmp_path))
        logger = _u.get_session_logger()
        assert logger.level == 30  # logging.WARNING

    def test_valid_level_string_does_not_warn(self, tmp_path):
        import warnings
        from logcrest import configure
        import logcrest.utils as _u
        configure(level="WARNING", name="lvl-ok", dir=str(tmp_path))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _u.get_session_logger()
        assert not any("unknown log level" in str(x.message).lower() for x in w)
