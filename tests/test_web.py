import io
import json
import re
import threading
import time
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from workflow.config import Settings, normalize_base_url
from workflow.mock import MockModel
from workflow.state import ModelUsage
from workflow.web import create_app
from workflow.web_models import ConnectionInput, check_connection

ROOT = Path(__file__).resolve().parent.parent


def test_workflow_save_load_and_invalid_topology_are_checked(client, task):
    definition = client.get("/api/bootstrap").json()["workflow_templates"][1]
    entry = client.post("/api/workflows/save", json={"definition": definition}).json()
    assert client.get("/api/workflows").json()["items"] == [entry]
    bad = json.loads(json.dumps(definition))
    next(e for e in bad["edges"] if e["source"] == "coder")["target"] = "gate"
    assert client.post("/api/workflows/validate", json=bad).status_code == 400
    assert (
        client.post(
            "/api/runs", json={"task": task.to_dict(), "mode": "mock", "workflow": bad}
        ).status_code
        == 400
    )
    assert client.get("/api/runs").json()["items"] == []
    response = client.post(
        "/api/runs", json={"task": task.to_dict(), "mode": "mock", "workflow": definition}
    )
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    report = wait_finished(client, run_id)
    assert report["status"] == "completed"
    assert report["workflow"] == definition
    assert len([n for n in report["node_runs"] if n["kind"] == "verifier"]) == 2
    assert client.get(f"/api/runs/{run_id}/download/workflow.json").json() == definition
    bundle = client.get(f"/api/runs/{run_id}/download/result.zip")
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        assert "workflow.json" in archive.namelist()


def test_workflow_changes_do_not_rewrite_a_run_snapshot(client, task):
    definition = client.get("/api/bootstrap").json()["workflow_templates"][0]
    entry = client.post("/api/workflows/save", json={"definition": definition}).json()
    response = client.post(
        "/api/runs", json={"task": task.to_dict(), "mode": "mock", "workflow": definition}
    )
    run_id = response.json()["run_id"]
    definition["name"] = "修改后的流程"
    assert (
        client.post(
            "/api/workflows/save", json={"id": entry["id"], "definition": definition}
        ).status_code
        == 200
    )
    report = wait_finished(client, run_id)
    assert report["workflow"]["name"] != definition["name"]


@pytest.fixture
def client(tmp_path):
    app = create_app(ROOT, tmp_path / "runs")
    with TestClient(app, base_url="http://127.0.0.1") as connection:
        page = connection.get("/")
        token = re.search(r'name="workflow-token"\s+content="([a-f0-9]+)"', page.text).group(1)
        connection.headers["X-Workflow-Token"] = token
        yield connection


def wait_finished(client, run_id):
    for _ in range(200):
        response = client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200
        report = response.json()
        if report["status"] not in {"running", "pending"}:
            return report
        time.sleep(0.02)
    pytest.fail("后台任务未在测试时限内结束")


def test_home_assets_and_examples_are_available(client):
    assert "把需求交给你的代码团队" in client.get("/").text
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/assets/style.css").status_code == 200
    assert client.get("/assets/graph-view.js").status_code == 200
    page = client.get("/").text
    assert page.index("/assets/graph-view.js") < page.index("/assets/graph-ui.js")
    assert 'id="graph-fit"' in page
    assert 'id="cancel-connection"' in page
    assert len(client.get("/api/bootstrap").json()["examples"]) == 3


def test_builtin_prompts_are_visible_and_match_the_runtime_prompts(client):
    from workflow.graph_runner import CUSTOM_PROMPT
    from workflow.prompts import CODER_PROMPT, FIXER_PROMPT, REVIEWER_PROMPT
    from workflow.verification import VERIFIER_PROMPT

    prompts = client.get("/api/bootstrap").json()["role_prompts"]
    assert prompts == {
        "coder": CODER_PROMPT,
        "reviewer": REVIEWER_PROMPT,
        "fixer": FIXER_PROMPT,
        "verifier": VERIFIER_PROMPT,
        "custom": CUSTOM_PROMPT,
    }
    assert all(prompts.values())
    assert 'value="auto"' not in client.get("/").text


def test_request_without_page_token_is_rejected(client):
    client.headers.pop("X-Workflow-Token")
    assert client.get("/api/runs").status_code == 403
    assert client.get("/api/health").status_code == 200


def test_cross_origin_and_foreign_host_are_rejected(client):
    assert (
        client.post(
            "/api/tasks/validate", json={}, headers={"Origin": "https://foreign.example"}
        ).status_code
        == 403
    )
    assert client.get("/", headers={"Host": "foreign.example"}).status_code == 403


def test_invalid_payload_does_not_echo_key(client):
    response = client.post(
        "/api/connection/validate",
        json={
            "api_key": {"private": "must-not-appear-in-response"},
            "model": "example",
        },
    )
    assert response.status_code == 422
    assert "must-not-appear-in-response" not in response.text


def test_connection_normalizes_full_url_without_returning_key(client):
    response = client.post(
        "/api/connection/validate",
        json={
            "api_key": "test-private-key",
            "base_url": "https://model.example/v1/chat/completions/",
            "model": "model-name",
        },
    )
    assert response.status_code == 200
    assert response.json()["base_url"] == "https://model.example/v1"
    assert "test-private-key" not in response.text


def test_local_model_can_omit_key_and_remote_model_cannot(client):
    assert (
        client.post(
            "/api/connection/validate",
            json={
                "base_url": "http://localhost:11434/v1",
                "model": "local-model",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/connection/validate",
            json={
                "base_url": "https://model.example/v1",
                "model": "remote-model",
            },
        ).status_code
        == 400
    )


def test_task_editor_validation_and_invalid_cases(client, task):
    assert client.post("/api/tasks/validate", json=task.to_dict()).status_code == 200
    data = task.to_dict()
    data["cases"] = []
    assert client.post("/api/tasks/validate", json=data).status_code == 400


def test_web_workflow_progress_history_and_downloads(client, task):
    response = client.post("/api/runs", json={"task": task.to_dict(), "mode": "mock"})
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    report = wait_finished(client, run_id)
    assert report["status"] == "completed"
    assert len(report["versions"]) == 2
    assert len(report["reviews"]) == 2
    assert report["reviews"][0]["review"]["issues"]
    assert not report["reviews"][1]["review"]["issues"]
    history = client.get("/api/runs").json()
    assert history["items"][0]["run_id"] == run_id
    assert client.get(f"/api/runs/{run_id}/download/final.py").status_code == 200
    bundle = client.get(f"/api/runs/{run_id}/download/result.zip")
    assert bundle.status_code == 200
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        assert "final.py" in archive.namelist()
        assert "report.md" in archive.namelist()
        assert "versions/v001.py" in archive.namelist()
    assert client.get(f"/api/runs/{run_id}/download/run.log").status_code == 404


def test_unresolved_web_run_has_non_success_state(client, task):
    response = client.post(
        "/api/runs",
        json={
            "task": task.to_dict(),
            "mode": "mock",
            "scenario": "stuck",
            "max_repairs": 1,
        },
    )
    report = wait_finished(client, response.json()["run_id"])
    assert report["status"] == "needs_changes"
    assert report["repair_count"] == 1


def test_real_run_requires_connection(client, task):
    assert client.post("/api/runs", json={"task": task.to_dict()}).status_code == 400


def test_large_payload_is_rejected_before_parsing(client):
    response = client.post(
        "/api/tasks/validate", content="x" * 512001, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


def test_old_pending_record_is_marked_interrupted(client, task, tmp_path):
    directory = tmp_path / "runs" / "old-run"
    directory.mkdir(parents=True)
    (directory / "report.json").write_text(
        json.dumps(
            {
                "task": task.to_dict(),
                "status": "running",
                "history": [],
            }
        ),
        encoding="utf-8",
    )
    assert client.get("/api/runs/old-run").json()["status"] == "interrupted"


def test_custom_requirement_preparation_preserves_user_description(tmp_path, task):
    class PreparationModel:
        name = "prepare-test"
        usage = ModelUsage()

        def complete(self, role, messages):
            data = task.to_dict()
            data["requirement"] = "model must not overwrite original requirement"
            return json.dumps(data, ensure_ascii=False)

        def close(self):
            pass

    app = create_app(ROOT, tmp_path / "runs", model_factory=lambda settings: PreparationModel())
    with TestClient(app, base_url="http://127.0.0.1") as connection:
        connection.headers["X-Workflow-Token"] = app.state.token
        response = connection.post(
            "/api/tasks/prepare",
            json={
                "requirement": "用户自己的原始描述",
                "connection": {"api_key": "test-only"},
            },
        )
        assert response.status_code == 200
        assert response.json()["needs_confirmation"]
        assert response.json()["task"]["requirement"] == "用户自己的原始描述"


def test_cancel_and_single_active_task(tmp_path, task):
    entered = threading.Event()
    release = threading.Event()

    class BlockingModel(MockModel):
        def complete(self, role, messages):
            entered.set()
            if not release.wait(timeout=5):
                raise RuntimeError("test did not release model")
            return super().complete(role, messages)

    app = create_app(ROOT, tmp_path / "runs", model_factory=lambda settings: BlockingModel(task))
    with TestClient(app, base_url="http://127.0.0.1") as connection:
        connection.headers["X-Workflow-Token"] = app.state.token
        payload = {"task": task.to_dict(), "connection": {"api_key": "test-only"}}
        try:
            first = connection.post("/api/runs", json=payload)
            assert first.status_code == 202
            assert entered.wait(timeout=2)
            assert connection.post("/api/runs", json=payload).status_code == 409
            run_id = first.json()["run_id"]
            assert connection.post(f"/api/runs/{run_id}/cancel").status_code == 200
        finally:
            release.set()
        assert wait_finished(connection, run_id)["status"] == "cancelled"


def test_real_web_run_does_not_persist_api_key(tmp_path, task):
    key = "web-test-secret-not-for-storage"
    app = create_app(ROOT, tmp_path / "runs", model_factory=lambda settings: MockModel(task))
    with TestClient(app, base_url="http://127.0.0.1") as connection:
        connection.headers["X-Workflow-Token"] = app.state.token
        response = connection.post(
            "/api/runs",
            json={
                "task": task.to_dict(),
                "connection": {"api_key": key},
            },
        )
        report = wait_finished(connection, response.json()["run_id"])
        assert report["status"] == "completed"
    for path in (tmp_path / "runs").rglob("*"):
        if path.is_file():
            assert key not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("key", ["line\nbreak", "contains space", "密钥"])
def test_invalid_key_characters_are_rejected(key):
    with pytest.raises(ValueError, match="无效字符"):
        ConnectionInput(api_key=key).settings()


def test_connection_probe_uses_models_endpoint_without_generating(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "example-model"}]})

    original = httpx.Client
    monkeypatch.setattr(
        "workflow.web_models.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = check_connection(Settings(api_key="test-only"))
    assert result["models"] == ["example-model"]
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/models"


def test_full_endpoint_and_ipv4_url_normalization():
    assert (
        normalize_base_url("http://127.0.0.1:11434/v1/chat/completions")
        == "http://127.0.0.1:11434/v1"
    )


@pytest.mark.parametrize("url", ["http://localhost:invalid/v1", "https://host name.example/v1"])
def test_invalid_url_ports_and_spaces_are_rejected(url):
    with pytest.raises(ValueError):
        normalize_base_url(url)
