"""
Security regression tests for log file permissions.

LogCrest documents that log files are created 0600 (owner read/write only).
This must hold not just for the initial file but for EVERY file the rotating
handler creates — including the post-rotation base file and all backups.

Regression: previously os.chmod ran once at handler creation, so files created
during rotation inherited the process umask (commonly 0644 = world-readable),
silently violating the documented guarantee in steady-state production.

Implementation target:
  logcrest/handlers.py — FileHandlerFactory must create a handler that opens
  every file (initial + rotated) with 0600 permissions.
"""
import os
import stat
import logging
import pytest
from pathlib import Path

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="POSIX file permission semantics required"
)


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def _make_handler(tmp_path, max_bytes, backup_count):
    from logcrest.handlers import FileHandlerFactory
    from logcrest.formatters import JSONFormatter
    f = tmp_path / "sub" / "app.log"
    return f, FileHandlerFactory(
        f, logging.DEBUG, [], JSONFormatter(),
        max_bytes=max_bytes, backup_count=backup_count,
    ).get_handler()


class TestInitialFilePermissions:
    def test_initial_log_file_is_0600(self, tmp_path):
        f, h = _make_handler(tmp_path, max_bytes=10_000, backup_count=3)
        assert _mode(f) == 0o600, f"Initial file must be 0600, got {oct(_mode(f))}"


class TestRotatedFilePermissions:
    def test_all_files_remain_0600_after_rotation(self, tmp_path):
        f, h = _make_handler(tmp_path, max_bytes=200, backup_count=3)
        logger = logging.getLogger("perm-rotation-test")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        logger.addHandler(h)
        try:
            for i in range(60):
                logger.info("x" * 50 + str(i))   # force several rollovers
        finally:
            h.close()
            logger.handlers.clear()

        produced = sorted((tmp_path / "sub").glob("*"))
        assert len(produced) >= 2, "Test must actually trigger rotation"
        for p in produced:
            assert _mode(p) == 0o600, (
                f"{p.name} must be 0600 after rotation, got {oct(_mode(p))} "
                f"(world/group-readable log file leaks stack traces)"
            )

    def test_post_rotation_base_file_is_0600(self, tmp_path):
        """The new base file created during rollover is the one most likely to regress."""
        f, h = _make_handler(tmp_path, max_bytes=200, backup_count=2)
        logger = logging.getLogger("perm-base-test")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        logger.addHandler(h)
        try:
            for i in range(40):
                logger.info("y" * 50 + str(i))
        finally:
            h.close()
            logger.handlers.clear()

        assert (tmp_path / "sub" / "app.log.1").exists(), "Rotation must have occurred"
        assert _mode(f) == 0o600, (
            f"Post-rotation base file must be 0600, got {oct(_mode(f))}"
        )
