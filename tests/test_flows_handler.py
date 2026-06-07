"""
TDD tests for the flows/ log handler and associated filters.

Subtask: 4ee094c0 — "Add flows/ log handler"

What we're building:
- FlowFilter   — passes only records where flow_type in ('flow_start', 'flow_end')
- NoFlowFilter — passes records without a flow_type; blocks flow records from
                 reaching success/ and error/ handlers
- A third FileHandlerFactory in AsyncLoggerBuilder._prepare_handlers() writing to
  {base_log_dir}/flows/{timestamp}_flows.log with FlowFilter attached
- NoFlowFilter added to the existing success/ and error/ handlers

Implementation targets:
  logcrest/config.py — add FlowFilter, NoFlowFilter
  logcrest/core.py   — add flows handler in _prepare_handlers()
"""
import json
import time
import logging
import pytest
from pathlib import Path
from logging.handlers import RotatingFileHandler


def make_builder(tmp_path: Path, log_name: str):
    from logcrest.core import AsyncLoggerBuilder
    cfg = tmp_path / f"{log_name}.json"
    cfg.write_text(json.dumps({
        "log_name": log_name,
        "base_log_dir": str(tmp_path / log_name / "logs"),
        "use_json": False,
    }))
    return AsyncLoggerBuilder(config_path=cfg)


def _make_record(flow_type=None, level=logging.INFO):
    r = logging.LogRecord(
        name="test", level=level, pathname="", lineno=0,
        msg="msg", args=(), exc_info=None,
    )
    if flow_type is not None:
        r.flow_type = flow_type
    return r


# ── Unit tests: FlowFilter ────────────────────────────────────────────────────

class TestFlowFilter:
    """FlowFilter must pass exactly flow_start and flow_end records."""

    def test_importable_from_config(self):
        from logcrest.config import FlowFilter
        assert FlowFilter is not None

    def test_passes_flow_start_records(self):
        from logcrest.config import FlowFilter
        r = _make_record(flow_type='flow_start')
        assert FlowFilter().filter(r) is True

    def test_passes_flow_end_records(self):
        from logcrest.config import FlowFilter
        r = _make_record(flow_type='flow_end')
        assert FlowFilter().filter(r) is True

    def test_blocks_records_without_flow_type(self):
        from logcrest.config import FlowFilter
        r = _make_record()  # no flow_type set
        assert FlowFilter().filter(r) is False

    def test_blocks_records_with_unknown_flow_type(self):
        from logcrest.config import FlowFilter
        r = _make_record(flow_type='other_value')
        assert FlowFilter().filter(r) is False

    def test_blocks_regular_log_decorator_records(self):
        """Records from @log_decorator have no flow_type — must be blocked."""
        from logcrest.config import FlowFilter
        r = _make_record()
        r.actual_func_name = 'my_fn'
        r.trace_id = 'abc12345'
        assert FlowFilter().filter(r) is False


# ── Unit tests: NoFlowFilter ─────────────────────────────────────────────────

class TestNoFlowFilter:
    """NoFlowFilter is the inverse: blocks flow records, passes everything else."""

    def test_importable_from_config(self):
        from logcrest.config import NoFlowFilter
        assert NoFlowFilter is not None

    def test_passes_records_without_flow_type(self):
        from logcrest.config import NoFlowFilter
        r = _make_record()
        assert NoFlowFilter().filter(r) is True

    def test_blocks_flow_start_records(self):
        from logcrest.config import NoFlowFilter
        r = _make_record(flow_type='flow_start')
        assert NoFlowFilter().filter(r) is False

    def test_blocks_flow_end_records(self):
        from logcrest.config import NoFlowFilter
        r = _make_record(flow_type='flow_end')
        assert NoFlowFilter().filter(r) is False

    def test_passes_records_with_unknown_flow_type(self):
        """Only the two known flow types are blocked — future types are not."""
        from logcrest.config import NoFlowFilter
        r = _make_record(flow_type='other_value')
        assert NoFlowFilter().filter(r) is True

    def test_passes_log_decorator_records(self):
        from logcrest.config import NoFlowFilter
        r = _make_record()
        r.actual_func_name = 'my_fn'
        assert NoFlowFilter().filter(r) is True


# ── Integration tests: handler configuration after build() ───────────────────

class TestFlowsHandlerInBuilder:
    """After build(), the listener must have a flows/ handler with FlowFilter,
    and success/ and error/ handlers must have NoFlowFilter attached."""

    def test_three_file_handlers_present_after_build(self, tmp_path):
        b = make_builder(tmp_path, "svc_flows_count")
        b.build()
        file_handlers = [h for h in b._listener.handlers if isinstance(h, RotatingFileHandler)]
        # success/, error/, flows/ = 3 file handlers
        assert len(file_handlers) == 3, (
            f"Expected 3 RotatingFileHandlers (success, error, flows), got {len(file_handlers)}"
        )

    def test_flows_handler_path_contains_flows_subdir(self, tmp_path):
        b = make_builder(tmp_path, "svc_flows_path")
        b.build()
        file_handlers = [h for h in b._listener.handlers if isinstance(h, RotatingFileHandler)]
        flows_handlers = [h for h in file_handlers if Path(h.baseFilename).parent.name == 'flows']
        assert len(flows_handlers) == 1, "Exactly one handler must write to a 'flows/' subdirectory"

    def test_flows_handler_has_flow_filter(self, tmp_path):
        from logcrest.config import FlowFilter
        b = make_builder(tmp_path, "svc_flows_filter")
        b.build()
        file_handlers = [h for h in b._listener.handlers if isinstance(h, RotatingFileHandler)]
        flows_h = next(h for h in file_handlers if Path(h.baseFilename).parent.name == 'flows')
        assert any(isinstance(f, FlowFilter) for f in flows_h.filters), (
            "flows/ handler must have FlowFilter attached"
        )

    def test_success_handler_has_no_flow_filter(self, tmp_path):
        from logcrest.config import NoFlowFilter
        b = make_builder(tmp_path, "svc_flows_success")
        b.build()
        file_handlers = [h for h in b._listener.handlers if isinstance(h, RotatingFileHandler)]
        success_h = next(h for h in file_handlers if Path(h.baseFilename).parent.name == 'success')
        assert any(isinstance(f, NoFlowFilter) for f in success_h.filters), (
            "success/ handler must have NoFlowFilter to exclude flow records"
        )

    def test_error_handler_has_no_flow_filter(self, tmp_path):
        from logcrest.config import NoFlowFilter
        b = make_builder(tmp_path, "svc_flows_error")
        b.build()
        file_handlers = [h for h in b._listener.handlers if isinstance(h, RotatingFileHandler)]
        error_h = next(h for h in file_handlers if Path(h.baseFilename).parent.name == 'error')
        assert any(isinstance(f, NoFlowFilter) for f in error_h.filters), (
            "error/ handler must have NoFlowFilter to exclude flow records"
        )

    def test_flows_handler_does_not_have_no_flow_filter(self, tmp_path):
        """Sanity check: the flows/ handler must not accidentally have NoFlowFilter."""
        from logcrest.config import NoFlowFilter
        b = make_builder(tmp_path, "svc_flows_sanity")
        b.build()
        file_handlers = [h for h in b._listener.handlers if isinstance(h, RotatingFileHandler)]
        flows_h = next(h for h in file_handlers if Path(h.baseFilename).parent.name == 'flows')
        assert not any(isinstance(f, NoFlowFilter) for f in flows_h.filters)


# ── End-to-end routing tests ─────────────────────────────────────────────────

class TestFlowRecordRouting:
    """Records with flow_type must reach flows/ only; regular records must not."""

    def _build_and_log(self, tmp_path, log_name, records_to_emit, wait=0.25):
        """Build a logger, emit records, flush, return the log base dir."""
        b = make_builder(tmp_path, log_name)
        logger = b.build()
        for msg, extra in records_to_emit:
            logger.info(msg, extra=extra)
        time.sleep(wait)
        b._listener.stop()
        base_dir = tmp_path / log_name / "logs"
        return base_dir

    def _read_file(self, path: Path) -> str:
        files = list(path.glob("*.log"))
        if not files:
            return ""
        return files[0].read_text()

    def test_flow_start_record_appears_in_flows_dir(self, tmp_path):
        marker = "MY_FLOW_START_MARKER"
        base_dir = self._build_and_log(tmp_path, "svc_e2e_flowstart", [
            (marker, {'flow_type': 'flow_start', 'flow_id': 'test-abc123'}),
        ])
        content = self._read_file(base_dir / "flows")
        assert marker in content, f"flow_start record must appear in flows/. Got:\n{content}"

    def test_flow_start_record_absent_from_success_dir(self, tmp_path):
        marker = "FLOW_ONLY_XYZ987"
        base_dir = self._build_and_log(tmp_path, "svc_e2e_no_success", [
            (marker, {'flow_type': 'flow_start', 'flow_id': 'test-abc456'}),
        ])
        content = self._read_file(base_dir / "success")
        assert marker not in content, f"flow_start record must NOT appear in success/. Got:\n{content}"

    def test_regular_record_appears_in_success_dir(self, tmp_path):
        marker = "REGULAR_INFO_MSG_567"
        base_dir = self._build_and_log(tmp_path, "svc_e2e_regular", [
            (marker, {}),
        ])
        content = self._read_file(base_dir / "success")
        assert marker in content, f"Regular INFO record must appear in success/. Got:\n{content}"

    def test_regular_record_absent_from_flows_dir(self, tmp_path):
        marker = "NO_FLOW_MSG_890"
        base_dir = self._build_and_log(tmp_path, "svc_e2e_no_flow", [
            (marker, {}),
        ])
        content = self._read_file(base_dir / "flows")
        assert marker not in content, f"Regular record must NOT appear in flows/. Got:\n{content}"

    def test_flow_end_record_appears_in_flows_dir(self, tmp_path):
        marker = "FLOW_END_MARKER_111"
        base_dir = self._build_and_log(tmp_path, "svc_e2e_flowend", [
            (marker, {'flow_type': 'flow_end', 'flow_status': 'success'}),
        ])
        content = self._read_file(base_dir / "flows")
        assert marker in content, f"flow_end record must appear in flows/. Got:\n{content}"
