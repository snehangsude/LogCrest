"""
Tests for ConfigManager: loading, validation, warnings, and env var overrides.

Covers existing behaviour plus two confirmed bugs:
  - Unknown config keys are silently ignored (no warning emitted)
  - Environment variables have no effect on config values

Fix targets:
  - logcrest/config.py :: ConfigManager._load() — warn on unknown keys
  - logcrest/config.py :: ConfigManager.get()   — read env vars with priority
"""
import os
import json
import warnings
import pytest
from pathlib import Path
from logcrest.config import ConfigManager


KNOWN_KEYS = {"base_log_dir", "max_log_size", "backup_count", "use_json", "log_name"}

ENV_MAP = {
    "log_name":     "LOGCREST_NAME",
    "base_log_dir": "LOGCREST_DIR",
    "use_json":     "LOGCREST_JSON",
    "max_log_size": "LOGCREST_MAX_SIZE",
    "backup_count": "LOGCREST_BACKUP_COUNT",
}


# ---------------------------------------------------------------------------
# Existing behaviour (must continue to pass after fixes)
# ---------------------------------------------------------------------------

class TestConfigDefaults:
    def test_returns_default_when_file_missing(self, tmp_path):
        config = ConfigManager(path=tmp_path / "nonexistent.json")
        assert config.get("log_name", "fallback") == "fallback"

    def test_returns_default_when_key_absent_from_file(self, tmp_path):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({"log_name": "myapp"}))
        config = ConfigManager(path=cfg)
        assert config.get("backup_count", 7) == 7

    def test_reads_string_value(self, tmp_path):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({"log_name": "prod_logger"}))
        config = ConfigManager(path=cfg)
        assert config.get("log_name", "") == "prod_logger"

    def test_reads_numeric_value(self, tmp_path):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({"max_log_size": 1048576}))
        config = ConfigManager(path=cfg)
        assert config.get("max_log_size", 0) == 1048576

    def test_reads_bool_value(self, tmp_path):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({"use_json": False}))
        config = ConfigManager(path=cfg)
        assert config.get("use_json", True) is False

    def test_warns_on_invalid_json(self, tmp_path):
        cfg = tmp_path / "c.json"
        cfg.write_text("{not valid json")
        with pytest.warns(UserWarning, match="invalid JSON"):
            config = ConfigManager(path=cfg)
        assert config.get("log_name", "default") == "default"

    def test_warns_on_unreadable_file(self, tmp_path):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({"log_name": "x"}))
        cfg.chmod(0o000)
        try:
            with pytest.warns(UserWarning):
                config = ConfigManager(path=cfg)
            assert config.get("log_name", "default") == "default"
        finally:
            cfg.chmod(0o644)


# ---------------------------------------------------------------------------
# Unknown key warnings (bug fix)
# ---------------------------------------------------------------------------

class TestUnknownKeyWarnings:
    def test_known_keys_do_not_trigger_warning(self, tmp_path):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({k: "x" for k in KNOWN_KEYS}))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ConfigManager(path=cfg)
        unknown_warns = [x for x in w if "unknown" in str(x.message).lower()]
        assert len(unknown_warns) == 0

    def test_single_unknown_key_emits_warning(self, tmp_path):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({"log_name": "ok", "max_log_siz": 999}))
        with pytest.warns(UserWarning, match="max_log_siz"):
            ConfigManager(path=cfg)

    def test_warning_message_names_the_bad_key(self, tmp_path):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({"typo_key": "val"}))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ConfigManager(path=cfg)
        messages = [str(x.message) for x in w]
        assert any("typo_key" in m for m in messages)

    def test_multiple_unknown_keys_each_emit_a_warning(self, tmp_path):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({"bad_a": 1, "bad_b": 2}))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ConfigManager(path=cfg)
        unknown_warns = [x for x in w if "unknown" in str(x.message).lower()]
        assert len(unknown_warns) == 2

    def test_unknown_keys_still_load_known_values_correctly(self, tmp_path):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({"log_name": "valid", "oops": "typo"}))
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            config = ConfigManager(path=cfg)
        assert config.get("log_name", "") == "valid"

    def test_no_warning_when_file_does_not_exist(self, tmp_path):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ConfigManager(path=tmp_path / "missing.json")
        unknown_warns = [x for x in w if "unknown" in str(x.message).lower()]
        assert len(unknown_warns) == 0


# ---------------------------------------------------------------------------
# Environment variable overrides (bug fix)
# ---------------------------------------------------------------------------

class TestEnvVarOverrides:
    @pytest.fixture(autouse=True)
    def clean_env(self):
        """Remove any LOGCREST_* env vars before and after each test."""
        for var in ENV_MAP.values():
            os.environ.pop(var, None)
        yield
        for var in ENV_MAP.values():
            os.environ.pop(var, None)

    def test_logcrest_name_overrides_file(self, tmp_path, monkeypatch):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({"log_name": "from_file"}))
        monkeypatch.setenv("LOGCREST_NAME", "from_env")
        config = ConfigManager(path=cfg)
        assert config.get("log_name", "") == "from_env"

    def test_logcrest_dir_overrides_file(self, tmp_path, monkeypatch):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({"base_log_dir": "/from/file"}))
        monkeypatch.setenv("LOGCREST_DIR", "/from/env")
        config = ConfigManager(path=cfg)
        assert config.get("base_log_dir", "") == "/from/env"

    def test_logcrest_json_false_string_becomes_bool_false(self, tmp_path, monkeypatch):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({"use_json": True}))
        monkeypatch.setenv("LOGCREST_JSON", "false")
        config = ConfigManager(path=cfg)
        assert config.get("use_json", True) is False

    def test_logcrest_json_true_string_becomes_bool_true(self, tmp_path, monkeypatch):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({"use_json": False}))
        monkeypatch.setenv("LOGCREST_JSON", "true")
        config = ConfigManager(path=cfg)
        assert config.get("use_json", False) is True

    def test_logcrest_max_size_string_becomes_int(self, tmp_path, monkeypatch):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({"max_log_size": 1000}))
        monkeypatch.setenv("LOGCREST_MAX_SIZE", "9999999")
        config = ConfigManager(path=cfg)
        assert config.get("max_log_size", 0) == 9999999
        assert isinstance(config.get("max_log_size", 0), int)

    def test_logcrest_backup_count_string_becomes_int(self, tmp_path, monkeypatch):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({}))
        monkeypatch.setenv("LOGCREST_BACKUP_COUNT", "10")
        config = ConfigManager(path=cfg)
        assert config.get("backup_count", 3) == 10
        assert isinstance(config.get("backup_count", 3), int)

    def test_env_var_works_without_config_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOGCREST_NAME", "env_only_app")
        config = ConfigManager(path=tmp_path / "nonexistent.json")
        assert config.get("log_name", "") == "env_only_app"

    def test_file_value_used_when_env_var_absent(self, tmp_path):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({"log_name": "from_file_only"}))
        config = ConfigManager(path=cfg)
        assert config.get("log_name", "") == "from_file_only"

    def test_default_used_when_neither_env_nor_file(self, tmp_path):
        config = ConfigManager(path=tmp_path / "nonexistent.json")
        assert config.get("log_name", "the_default") == "the_default"

    def test_env_var_takes_priority_over_both_file_and_default(self, tmp_path, monkeypatch):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({"log_name": "from_file"}))
        monkeypatch.setenv("LOGCREST_NAME", "from_env")
        config = ConfigManager(path=cfg)
        # env > file > default — env must win
        assert config.get("log_name", "from_default") == "from_env"

    def test_logcrest_json_case_insensitive(self, tmp_path, monkeypatch):
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({}))
        monkeypatch.setenv("LOGCREST_JSON", "FALSE")
        config = ConfigManager(path=cfg)
        assert config.get("use_json", True) is False
