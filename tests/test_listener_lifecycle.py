"""
TDD tests for the _listener class-variable bug in AsyncLoggerBuilder.

Bug: _listener is a class variable. When two builders are created with different
logger names, the second build() overwrites AsyncLoggerBuilder._listener so the
first builder's listener is inaccessible via the instance. This breaks test
isolation and any multi-logger use case.

Fix target: logcrest/core.py :: AsyncLoggerBuilder — change _listener to instance var.
"""
import json
import atexit
import logging
import pytest
from pathlib import Path
from unittest.mock import patch
from logcrest.core import AsyncLoggerBuilder


def make_builder(tmp_path: Path, log_name: str) -> AsyncLoggerBuilder:
    cfg = tmp_path / f"{log_name}.json"
    cfg.write_text(json.dumps({
        "log_name": log_name,
        "base_log_dir": str(tmp_path / log_name / "logs"),
    }))
    return AsyncLoggerBuilder(config_path=cfg)


# ---------------------------------------------------------------------------
# Instance variable ownership
# ---------------------------------------------------------------------------

class TestListenerIsInstanceVariable:
    def test_listener_accessible_on_instance_after_build(self, tmp_path):
        b = make_builder(tmp_path, "svc_a_lifecycle")
        b.build()
        assert b._listener is not None

    def test_two_builders_have_independent_listeners(self, tmp_path):
        b1 = make_builder(tmp_path, "svc_b1_lifecycle")
        b2 = make_builder(tmp_path, "svc_b2_lifecycle")
        b1.build()
        b2.build()

        assert b1._listener is not b2._listener, (
            "Each AsyncLoggerBuilder instance must own its own QueueListener. "
            "Class-variable sharing means b1._listener gets overwritten by b2's build()."
        )

    def test_class_variable_not_used_as_shared_state(self, tmp_path):
        """After fix, _listener must not live on the class dict."""
        b = make_builder(tmp_path, "svc_c_lifecycle")
        b.build()
        # If _listener is an instance var, it must be in the instance __dict__
        assert "_listener" in b.__dict__, (
            "_listener should be an instance attribute, not a class attribute"
        )

    def test_listener_starts_on_build(self, tmp_path):
        b = make_builder(tmp_path, "svc_d_lifecycle")
        b.build()
        # QueueListener sets _thread when started; None means not started
        assert b._listener._thread is not None and b._listener._thread.is_alive()

    def test_listener_stops_cleanly(self, tmp_path):
        b = make_builder(tmp_path, "svc_e_lifecycle")
        b.build()
        thread = b._listener._thread
        assert thread is not None and thread.is_alive()
        b._listener.stop()
        # QueueListener.stop() joins the thread then sets _thread=None
        assert b._listener._thread is None
        assert not thread.is_alive()


# ---------------------------------------------------------------------------
# Atexit registration
# ---------------------------------------------------------------------------

class TestAtexitRegistration:
    def test_atexit_registered_once_per_build(self, tmp_path):
        """Each build() registers exactly one atexit callback for its listener."""
        b = make_builder(tmp_path, "svc_f_lifecycle")
        with patch("logcrest.core.atexit") as mock_atexit:
            b.build()
            assert mock_atexit.register.call_count == 1
            registered_fn = mock_atexit.register.call_args[0][0]
            # The registered function must be the instance's listener stop, not the class's
            assert registered_fn == b._listener.stop

    def test_second_build_same_logger_name_skips_new_listener(self, tmp_path):
        """If the logger already has handlers, build() must not create a second listener."""
        b1 = make_builder(tmp_path, "svc_g_lifecycle")
        b2 = make_builder(tmp_path, "svc_g_lifecycle")  # same log_name

        with patch("logcrest.core.atexit") as mock_atexit:
            b1.build()
            b2.build()  # logger already has handlers — must be a no-op
            assert mock_atexit.register.call_count == 1, (
                "build() on an already-configured logger should not register a second atexit"
            )


# ---------------------------------------------------------------------------
# No cross-instance contamination
# ---------------------------------------------------------------------------

class TestNoClassStatePollution:
    def test_stopping_one_listener_does_not_affect_other(self, tmp_path):
        b1 = make_builder(tmp_path, "svc_h1_lifecycle")
        b2 = make_builder(tmp_path, "svc_h2_lifecycle")
        b1.build()
        b2.build()

        b2_thread = b2._listener._thread
        b1._listener.stop()

        # b1's listener thread is gone; b2's is still alive
        assert b1._listener._thread is None
        assert b2_thread.is_alive(), (
            "Stopping b1's listener must not affect b2's listener"
        )
        b2._listener.stop()

    def test_listener_not_none_before_build(self, tmp_path):
        """Before build(), instance _listener should not already be set by a prior instance."""
        b1 = make_builder(tmp_path, "svc_i1_lifecycle")
        b1.build()

        b2 = make_builder(tmp_path, "svc_i2_lifecycle")
        # b2 not built yet — its _listener must reflect its own unbuilt state
        assert getattr(b2, "_listener", None) is None, (
            "A fresh builder that has not been built must have _listener=None"
        )
