import json
from pathlib import Path

import httpx
import pytest

from workflow.artifacts import RunStore
from workflow.config import Settings
from workflow.errors import ModelError
from workflow.llm import ChatModel
from workflow.mock import MockModel
from workflow.runner import Workflow
from workflow.state import ModelUsage, ValidationResult, WorkflowState
from workflow.task import load_task
from workflow.tools import CodeValidator

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("task_id", ["average", "deduplicate", "factorial"])
@pytest.mark.parametrize(
    "scenario,expected,repairs",
    [
        ("repair", "completed", 1),
        ("pass", "completed", 0),
        ("stuck", "needs_changes", 2),
    ],
)
def test_end_to_end_paths(task_id, scenario, expected, repairs):
    task = load_task(ROOT / "examples" / f"{task_id}.json")
    state = Workflow(MockModel(task, scenario)).run(WorkflowState(task))
    assert state.status == expected
    assert state.repair_count == repairs
    assert state.validation.code_version == state.code_version
    assert state.started_at and state.finished_at
    assert state.usage.requests > 0


def test_repair_invalidates_previous_results_and_preserves_snapshots(task, tmp_path):
    store = RunStore(tmp_path)
    state = Workflow(MockModel(task)).run(WorkflowState(task), store.record)
    store.finish(state)
    snapshots = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((store.path / "snapshots").glob("*.json"))
    ]
    first_check = next(item for item in snapshots if item["history"][-1]["stage"] == "validate")
    repaired = next(item for item in snapshots if item["history"][-1]["stage"] == "fixer")
    assert first_check["validation"]["passed"] is False
    assert first_check["code_version"] == 1
    assert repaired["code_version"] == 2
    assert repaired["review"] is None and repaired["validation"] is None
    assert (store.path / "initial.py").read_text() != (store.path / "final.py").read_text()
    assert len(list((store.path / "versions").glob("*.py"))) == 2
    assert len((store.path / "events.jsonl").read_text(encoding="utf-8").splitlines()) == len(
        state.history
    )


def test_zero_repairs_stops_after_initial_review(task):
    state = Workflow(MockModel(task)).run(WorkflowState(task, max_repairs=0))
    assert state.status == "needs_changes"
    assert state.repair_count == 0
    assert all(event.stage != "fixer" for event in state.history)


def test_model_failure_is_recorded(task):
    class BrokenModel:
        name = "broken-test"
        usage = ModelUsage()

        def complete(self, role, messages):
            raise ModelError("模拟连接失败")

    state = Workflow(BrokenModel()).run(WorkflowState(task))
    assert state.status == "failed"
    assert "模拟连接失败" in state.error
    assert state.history[-1].stage == "error"


def test_review_cannot_override_failing_validation(task):
    class SilentReviewer(MockModel):
        def complete(self, role, messages):
            if role == "reviewer":
                return json.dumps({"summary": "无问题", "issues": []})
            return super().complete(role, messages)

    state = Workflow(SilentReviewer(task)).run(WorkflowState(task, max_repairs=0))
    assert state.status == "needs_changes"
    assert not state.validation.passed


def test_reviewer_findings_block_completion_even_when_tests_pass(task):
    class StrictReviewer(MockModel):
        def complete(self, role, messages):
            if role == "reviewer":
                return json.dumps(
                    {
                        "summary": "仍有问题",
                        "issues": [
                            {
                                "severity": "low",
                                "line": None,
                                "message": "额外问题",
                                "evidence": "具体证据",
                                "suggestion": "具体建议",
                            }
                        ],
                    }
                )
            return super().complete(role, messages)

    state = Workflow(StrictReviewer(task, "pass")).run(WorkflowState(task, max_repairs=0))
    assert state.validation.passed
    assert state.status == "needs_changes"


def test_stale_validation_is_rejected(task):
    class StaleValidator(CodeValidator):
        def validate(self, task, code, version):
            return ValidationResult(version - 1, "wrong-hash", True, "旧验证")

    state = Workflow(MockModel(task), StaleValidator()).run(WorkflowState(task))
    assert state.status == "failed"
    assert "不匹配" in state.error


def test_completed_state_cannot_be_reused(task):
    workflow = Workflow(MockModel(task, "pass"))
    state = workflow.run(WorkflowState(task))
    with pytest.raises(ValueError, match="新的 WorkflowState"):
        workflow.run(state)


def test_real_http_adapter_and_agents_integrate_without_external_network(task):
    mock = MockModel(task)

    def respond(request):
        body = json.loads(request.content)
        prompt = body["messages"][0]["content"]
        role = (
            "coder"
            if "你是编码 Agent" in prompt
            else ("reviewer" if "你是独立的代码审查 Agent" in prompt else "fixer")
        )
        content = mock.complete(role, body["messages"])
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            },
        )

    model = ChatModel(
        Settings(api_key="test-only-not-a-real-key"), transport=httpx.MockTransport(respond)
    )
    try:
        state = Workflow(model).run(WorkflowState(task))
        assert state.status == "completed"
        assert state.usage.requests == 4
        assert state.usage.prompt_tokens == 40
        assert state.usage.completion_tokens == 80
        assert "test-only-not-a-real-key" not in json.dumps(state.to_dict())
    finally:
        model.close()
