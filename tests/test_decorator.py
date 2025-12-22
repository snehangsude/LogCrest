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
