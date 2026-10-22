import json

import pytest

from workflow.agents import CodingAgent, ReviewAgent, parse_review
from workflow.errors import OutputError
from workflow.mock import MockModel
from workflow.state import ModelUsage, ValidationResult


class ScriptModel:
    name = "script-test"

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.usage = ModelUsage()
        self.messages = []

    def complete(self, role, messages):
        self.usage.requests += 1
        self.messages.append(list(messages))
        return next(self.outputs)


def test_output_format_recovery_preserves_task(task):
    model = ScriptModel(
        ["not json", json.dumps({"code": "def average(numbers): return 0", "summary": "示例"})]
    )
    result = CodingAgent(model).run(task)
    assert result.code.startswith("def average")
    assert model.usage.requests == 2
    assert "格式校验失败" in model.messages[1][-1]["content"]
    assert json.loads(model.messages[1][1]["content"])["task"]["id"] == task.id


@pytest.mark.parametrize(
    "raw",
    [
        "{}",
        "[]",
        '{"code":"","summary":"empty"}',
        '{"code":"def f(): pass","summary":"ok","extra":1}',
    ],
)
def test_invalid_output_fails_with_bounded_attempts(task, raw):
    model = ScriptModel([raw, raw])
    with pytest.raises(OutputError):
        CodingAgent(model).run(task)
    assert model.usage.requests == 2


def test_review_contains_requirement_code_and_current_evidence(task):
    model = ScriptModel([json.dumps({"summary": "无问题", "issues": []})])
    validation = ValidationResult(3, "hash", True, "通过")
    ReviewAgent(model).run(task, "def average(numbers): return 0", 3, validation)
    payload = json.loads(model.messages[0][1]["content"])
    assert payload["task"]["requirement"] == task.requirement
    assert payload["code_version"] == payload["validation"]["code_version"] == 3
    assert payload["code"]


def test_invalid_issue_line_is_rejected():
    with pytest.raises(ValueError, match="有效行号"):
        parse_review(
            {
                "summary": "问题",
                "issues": [
                    {
                        "severity": "medium",
                        "line": 99,
                        "message": "问题",
                        "evidence": "证据",
                        "suggestion": "建议",
                    }
                ],
            },
            3,
        )


def test_mock_rejects_modified_task(task):
    data = task.to_dict()
    data["requirement"] += "额外需求"
    with pytest.raises(ValueError, match="自定义任务"):
        MockModel(type(task).from_dict(data))
