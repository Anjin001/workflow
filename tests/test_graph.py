import json
from copy import deepcopy

import pytest

from workflow.graph import Edge, GraphLibrary, Node, default_graph, parse_graph
from workflow.graph_runner import GraphWorkflow
from workflow.mock import MockModel
from workflow.state import WorkflowState


def insert(graph, source, target, identifier="analyst", inputs=None):
    graph.nodes.append(
        Node(
            id=identifier,
            kind="custom",
            name=identifier,
            prompt="对照任务分析上游结果并给出建议。",
            inputs=inputs or ["task", "upstream"],
        )
    )
    edge = next(e for e in graph.edges if e.source == source and e.target == target)
    graph.edges.remove(edge)
    graph.edges += [
        Edge(source=source, target=identifier, condition=edge.condition),
        Edge(source=identifier, target=target),
    ]
    return graph


@pytest.mark.parametrize("verified", [False, True])
def test_templates_compile_and_run_real_acceptance(task, verified):
    graph = parse_graph(default_graph(verified).model_dump())
    result = GraphWorkflow(MockModel(task), graph).run(WorkflowState(task))
    assert result.status == "completed", result.error
    assert result.repair_count == 1
    assert result.validation.passed
    assert len([n for n in result.node_runs if n["kind"] == "validate"]) == 2
    assert result.workflow == graph.model_dump()
    if verified:
        verifications = [n["output"] for n in result.node_runs if n["kind"] == "verifier"]
        assert verifications[0]["findings"][0]["verdict"] == "confirmed"
        assert verifications[1]["findings"] == []


@pytest.mark.parametrize(
    "problem",
    [
        "duplicate",
        "orphan",
        "cycle",
        "skip_validation",
        "missing_edge",
        "unknown_target",
        "bad_input",
        "blank_prompt",
        "bad_repair",
    ],
)
def test_invalid_graph_is_blocked_before_execution(problem):
    graph = default_graph()
    if problem == "duplicate":
        graph.nodes.append(graph.nodes[0].model_copy())
    elif problem == "orphan":
        graph.nodes.append(Node(id="orphan", kind="custom", name="孤立", prompt="分析"))
        graph.edges.append(Edge(source="orphan", target="end"))
    elif problem == "cycle":
        next(e for e in graph.edges if e.source == "coder").target = "coder"
    elif problem == "skip_validation":
        next(e for e in graph.edges if e.source == "coder").target = "reviewer"
    elif problem == "missing_edge":
        graph.edges.pop()
    elif problem == "unknown_target":
        graph.edges[0].target = "missing"
    elif problem == "bad_input":
        insert(graph, "start", "coder", inputs=["code", "upstream"])
    elif problem == "blank_prompt":
        insert(graph, "coder", "validate").nodes[-1].prompt = " "
    else:
        next(e for e in graph.edges if e.source == "fixer").target = "coder"
    with pytest.raises(ValueError):
        parse_graph(graph.model_dump())


def test_repaired_code_cannot_read_previous_validation():
    graph = insert(default_graph(), "fixer", "validate", inputs=["validation", "upstream"])
    with pytest.raises(ValueError, match="尚未产生"):
        parse_graph(graph.model_dump())


def test_custom_nodes_use_edges_to_pass_outputs_and_cannot_change_code(task):
    graph = insert(default_graph(), "start", "coder", "requirements")
    graph = insert(graph, "requirements", "coder", "second")

    class RecordingModel(MockModel):
        def __init__(self):
            super().__init__(task)
            self.calls = []

        def complete(self, role, messages):
            payload = json.loads(messages[1]["content"])
            self.calls.append((role, deepcopy(payload)))
            if role == "custom":
                self.usage.requests += 1
                return json.dumps(
                    {"summary": "validated-analysis", "recommendations": ["保留原始接口"]}
                )
            return super().complete(role, messages)

    model = RecordingModel()
    runner = GraphWorkflow(model, graph)
    graph.nodes[-1].prompt = "修改外部画布不会影响本次快照"
    result = runner.run(WorkflowState(task))
    assert result.status == "completed"
    assert [role for role, _ in model.calls[:3]] == ["custom", "custom", "coder"]
    assert model.calls[1][1]["upstream"]["node_id"] == "requirements"
    assert model.calls[2][1]["workflow_context"]["upstream"]["node_id"] == "second"
    assert (
        model.calls[2][1]["workflow_context"]["upstream"]["output"]["summary"]
        == "validated-analysis"
    )
    assert result.workflow["nodes"][-1]["prompt"] != graph.nodes[-1].prompt


def test_step_limit_stops_before_success(task):
    graph = default_graph()
    graph.max_steps = 10
    state = GraphWorkflow(MockModel(task, "stuck"), graph).run(WorkflowState(task, 10))
    assert state.status == "needs_changes"
    assert len(state.node_runs) == 10
    assert "步数上限" in state.history[-1].message


def test_analysis_crosses_tool_node_but_not_a_code_revision(task):
    graph = insert(default_graph(), "coder", "validate", "boundary")

    class RecordingModel(MockModel):
        def __init__(self):
            super().__init__(task)
            self.reviews = []

        def complete(self, role, messages):
            if role == "reviewer":
                self.reviews.append(json.loads(messages[1]["content"])["workflow_context"])
            return super().complete(role, messages)

    model = RecordingModel()
    result = GraphWorkflow(model, graph).run(WorkflowState(task))
    assert result.status == "completed"
    assert model.reviews[0]["upstream"]["node_id"] == "validate"
    assert model.reviews[0]["upstream"]["advice"][0]["node_id"] == "boundary"
    assert model.reviews[0]["upstream"]["advice"][0]["code_version"] == 1
    assert model.reviews[1]["upstream"]["advice"] == []


def test_custom_description_and_prompt_are_saved_and_sent_to_model(task):
    graph = insert(default_graph(), "start", "coder", "analyst")
    graph.nodes[-1].description = "只分析需求中的边界条件。"
    graph.nodes[-1].prompt = "列出空输入与异常情况，并分别给出依据。"

    class CaptureModel(MockModel):
        system_prompt = ""

        def complete(self, role, messages):
            if role == "custom":
                self.system_prompt = messages[0]["content"]
            return super().complete(role, messages)

    model = CaptureModel(task)
    result = GraphWorkflow(model, graph).run(WorkflowState(task))
    assert result.status == "completed"
    assert graph.nodes[-1].description in model.system_prompt
    assert graph.nodes[-1].prompt in model.system_prompt
    assert result.workflow["nodes"][-1]["description"] == graph.nodes[-1].description


def test_custom_node_after_gate_executes_only_on_pass(task):
    graph = insert(default_graph(), "gate", "end", "docs")
    result = GraphWorkflow(MockModel(task, "stuck"), graph).run(WorkflowState(task, 0))
    assert not any(r["node_id"] == "docs" for r in result.node_runs)
    result = GraphWorkflow(MockModel(task), graph).run(WorkflowState(task))
    assert result.status == "completed"
    assert result.node_runs[-2]["node_id"] == "docs"


def test_saved_definitions_roundtrip_without_path_escape(tmp_path):
    library = GraphLibrary(tmp_path / "workflows")
    entry = library.save(default_graph().model_dump())
    assert library.list() == [entry]
    with pytest.raises(ValueError):
        library.save(default_graph().model_dump(), "../other")
    changed = default_graph().model_dump()
    changed["name"] = "另一个名称"
    assert library.save(changed, entry["id"])["id"] == entry["id"]
    assert len(library.list()) == 1
