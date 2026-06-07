import asyncio
import pytest
from unittest.mock import patch
from logcrest.decorator import log_decorator, INFO, DEBUG


@patch("logcrest.decorator.log")
def test_decorator_root_call(mock_log):
    @log_decorator
    def sample_func(a, b):
        return a + b

    result = sample_func(1, 2)
    assert result == 3
    assert mock_log.log.call_count >= 2

    first_call_args = mock_log.log.call_args_list[0][0]
    assert "Invoking 'sample_func'" in str(first_call_args[1])


@patch("logcrest.decorator.log")
def test_decorator_args_suppressed_by_default(mock_log):
    @log_decorator
    def login(username, password):
        return True

    login("admin", "s3cr3t")

    all_log_text = str(mock_log.log.call_args_list)
    assert "s3cr3t" not in all_log_text
    assert "admin" not in all_log_text


@patch("logcrest.decorator.log")
def test_decorator_log_args_explicit(mock_log):
    @log_decorator(log_args=True)
    def sample_func(a, b):
        return a + b

    sample_func(1, 2)

    first_call_args = mock_log.log.call_args_list[0][0]
    assert "args=(1, 2)" in str(first_call_args[1])


@patch("logcrest.decorator.log")
def test_decorator_nested_trace(mock_log):
    @log_decorator
    def child():
        return "child"

    @log_decorator
    def parent():
        return child()

    parent()

    call_1_extra = mock_log.log.call_args_list[0][1]["extra"]
    call_2_extra = mock_log.log.call_args_list[1][1]["extra"]
    assert call_1_extra["trace_id"] == call_2_extra["trace_id"]


@patch("logcrest.decorator.log")
def test_decorator_exception(mock_log):
    @log_decorator
    def fail():
        raise ValueError("Oops")

    with pytest.raises(ValueError):
        fail()

    assert mock_log.error.called
    error_msg = str(mock_log.error.call_args[0][0])
    assert "crashed after" in error_msg


@patch("logcrest.decorator.log")
def test_decorator_async_basic(mock_log):
    @log_decorator
    async def async_task(x):
        return x * 2

    result = asyncio.run(async_task(5))
    assert result == 10
    assert mock_log.log.call_count >= 2

    first_call_args = mock_log.log.call_args_list[0][0]
    assert "Invoking 'async_task'" in str(first_call_args[1])


@patch("logcrest.decorator.log")
def test_decorator_async_args_suppressed_by_default(mock_log):
    @log_decorator
    async def async_login(username, password):
        return True

    asyncio.run(async_login("admin", "s3cr3t"))

    all_log_text = str(mock_log.log.call_args_list)
    assert "s3cr3t" not in all_log_text


@patch("logcrest.decorator.log")
def test_decorator_async_exception(mock_log):
    @log_decorator
    async def async_fail():
        raise RuntimeError("async boom")

    with pytest.raises(RuntimeError):
        asyncio.run(async_fail())

    assert mock_log.error.called
    assert "crashed after" in str(mock_log.error.call_args[0][0])


@patch("logcrest.decorator.log")
def test_decorator_async_nested_trace(mock_log):
    @log_decorator
    async def async_child():
        return "done"

    @log_decorator
    async def async_parent():
        return await async_child()

    asyncio.run(async_parent())

    call_1_extra = mock_log.log.call_args_list[0][1]["extra"]
    call_2_extra = mock_log.log.call_args_list[1][1]["extra"]
    assert call_1_extra["trace_id"] == call_2_extra["trace_id"]


@patch("logcrest.decorator.log")
def test_decorator_async_with_level(mock_log):
    @log_decorator(DEBUG)
    async def debug_task():
        return 42

    result = asyncio.run(debug_task())
    assert result == 42
    assert mock_log.log.call_args_list[0][0][0] == DEBUG
