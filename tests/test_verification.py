import json

import pytest

from workflow.graph import default_graph
from workflow.graph_runner import GraphWorkflow
from workflow.mock import MockModel
from workflow.state import WorkflowState


class FindingModel(MockModel):
    def __init__(self, task, verdict="rejected", quote="def average(numbers):", scenario="pass"):
        super().__init__(task, scenario)
        self.verdict = verdict
        self.quote = quote
        self.fix_payloads = []

    def complete(self, role, messages):
        payload = json.loads(messages[1]["content"])
        if role == "reviewer":
            self.usage.requests += 1
            return json.dumps(
                {
                    "summary": "待验证候选",
                    "issues": [
                        {
                            "severity": "medium",
                            "line": 1,
                            "message": "候选问题",
                            "evidence": "待核实",
                            "suggestion": "依据需求检查",
                        }
                    ],
                }
            )
        if role == "verifier":
            self.usage.requests += 1
            return json.dumps(
                {
                    "summary": "独立验证",
                    "findings": [
                        {
                            "id": "F001",
                            "verdict": self.verdict,
                            "reason": "这是测试模型返回的证据说明",
                            "source_quote": self.quote,
                        }
                    ],
                }
            )
        if role == "fixer":
            self.fix_payloads.append(payload)
        return super().complete(role, messages)


def test_rejected_candidate_is_retained_but_does_not_force_repair(task):
    result = GraphWorkflow(FindingModel(task), default_graph(True)).run(WorkflowState(task))
    assert result.status == "completed"
    assert result.review.issues
    assert result.verification["findings"][0]["verdict"] == "rejected"
    assert result.repair_count == 0


@pytest.mark.parametrize(
    "verdict,quote",
    [("uncertain", ""), ("confirmed", "nonexistent source"), ("rejected", "nonexistent source")],
)
def test_uncertainty_or_fabricated_quote_cannot_pass(task, verdict, quote):
    result = GraphWorkflow(FindingModel(task, verdict, quote), default_graph(True)).run(
        WorkflowState(task)
    )
    assert result.status == "needs_review"
    assert result.verification["findings"][0]["verdict"] == "uncertain"
    assert result.repair_count == 0


def test_failed_acceptance_cannot_be_overruled_by_rejection(task):
    model = FindingModel(task, scenario="repair")
    result = GraphWorkflow(model, default_graph(True)).run(WorkflowState(task))
    assert result.status == "completed"
    assert result.repair_count == 1
    assert not model.fix_payloads[0]["review"]["issues"]
    assert not model.fix_payloads[0]["validation"]["passed"]


def test_confirmed_issue_is_bounded_by_repair_budget(task):
    result = GraphWorkflow(FindingModel(task, "confirmed"), default_graph(True)).run(
        WorkflowState(task, 1)
    )
    assert result.status == "needs_changes"
    assert result.repair_count == 1


def test_existing_quote_at_different_line_does_not_confirm_location(task):
    result = GraphWorkflow(
        FindingModel(task, "confirmed", "    if not numbers:"), default_graph(True)
    ).run(WorkflowState(task))
    assert result.status == "needs_review"
    assert result.verification["findings"][0]["quote_exists"]
    assert not result.verification["findings"][0]["location_matches"]


def test_missing_finding_verdict_fails_instead_of_silently_passing(task):
    class MissingModel(FindingModel):
        def complete(self, role, messages):
            if role == "verifier":
                return '{"summary":"忽略问题","findings":[]}'
            return super().complete(role, messages)

    result = GraphWorkflow(MissingModel(task), default_graph(True), output_retries=0).run(
        WorkflowState(task)
    )
    assert result.status == "failed"
    assert "全部候选问题" in result.error
