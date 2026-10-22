import pytest

from workflow.mock import FIXTURES
from workflow.task import TaskSpec
from workflow.tools import CodeValidator


@pytest.mark.parametrize(
    "code,reason",
    [
        ("def average(:", "语法"),
        ("def other(): return 0", "未在顶层"),
        ("async def average(numbers): return 0", "同步函数"),
        ("def average(numbers):\n    raise RuntimeError('failure')", "0/5"),
    ],
)
def test_invalid_implementations_fail(task, code, reason):
    result = CodeValidator().validate(task, code, 1)
    assert not result.passed
    assert reason in result.details


def test_infinite_loop_times_out(task):
    result = CodeValidator(timeout=1).validate(
        task, "def average(numbers):\n    while True: pass", 1
    )
    assert not result.passed
    assert "超过 1 秒" in result.details


def test_input_mutation_is_detected(task):
    code = """def average(numbers):
    value = sum(numbers) / len(numbers) if numbers else 0
    numbers.clear()
    return value
"""
    result = CodeValidator().validate(task, code, 1)
    assert not result.passed
    assert "修改" in result.cases[0]["detail"]


def test_numeric_tolerance_and_keywords_work(task):
    result = CodeValidator().validate(task, FIXTURES["average"][1], 2)
    assert result.passed
    assert result.cases[-1]["passed"]


def test_expected_exception_does_not_pass_on_normal_return():
    task = TaskSpec.from_dict(
        {
            "id": "raise",
            "requirement": "拒绝负数",
            "function_name": "f",
            "cases": [{"name": "负数", "args": [-1], "raises": "ValueError"}],
        }
    )
    result = CodeValidator().validate(task, "def f(n): return 0", 1)
    assert not result.passed


def test_boolean_does_not_satisfy_numeric_expected_value():
    task = TaskSpec.from_dict(
        {
            "id": "number",
            "requirement": "返回 1",
            "function_name": "f",
            "cases": [{"name": "数字", "expected": 1}],
        }
    )
    assert not CodeValidator().validate(task, "def f(): return True", 1).passed
