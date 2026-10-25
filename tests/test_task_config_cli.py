import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import main
from scripts.package_source import build_archive
from workflow.config import Settings
from workflow.task import TaskSpec


@pytest.mark.parametrize(
    "change",
    [
        {"function_name": "class"},
        {"cases": []},
        {"cases": [{"name": "both", "expected": 1, "raises": "ValueError"}]},
        {"cases": [{"name": "invalid-error", "raises": []}]},
        {"cases": [{"name": "bad-tolerance", "expected": 1, "tolerance": True}]},
        {"cases": [{"name": "bad-args", "expected": 1, "args": {}}]},
    ],
)
def test_invalid_task_is_rejected(task, change):
    data = task.to_dict()
    data.update(change)
    with pytest.raises(ValueError):
        TaskSpec.from_dict(data)


def clear_settings(monkeypatch):
    for name in list(os.environ):
        if name.startswith("LLM_") or name in {
            "DEEPSEEK_API_KEY",
            "OUTPUT_RETRIES",
            "TEST_TIMEOUT",
        }:
            monkeypatch.delenv(name)


def test_environment_overrides_dotenv_without_exposing_secret(tmp_path, monkeypatch):
    clear_settings(monkeypatch)
    (tmp_path / ".env").write_text("LLM_API_KEY=dotenv-test-value\nLLM_MODEL=file-model\n")
    monkeypatch.setenv("LLM_MODEL", "environment-model")
    settings = Settings.load(tmp_path)
    assert settings.model == "environment-model"
    assert settings.api_key == "dotenv-test-value"
    assert "dotenv-test-value" not in repr(settings)


@pytest.mark.parametrize(
    "url",
    ["http://remote.example", "https://user:pass@example.com", "https://example.com?key=secret"],
)
def test_unsafe_base_urls_are_rejected(tmp_path, monkeypatch, url):
    clear_settings(monkeypatch)
    monkeypatch.setenv("LLM_BASE_URL", url)
    with pytest.raises(ValueError):
        Settings.load(tmp_path)


def test_cli_saves_reports_and_returns_success(tmp_path, capsys):
    assert main.main(["--mock", "--output", str(tmp_path)]) == 0
    run = next(tmp_path.iterdir())
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "completed"
    assert (run / "report.md").exists()
    assert (run / "run.log").exists()
    assert "报告" in capsys.readouterr().out


def test_cli_returns_nonzero_for_unresolved_problem(tmp_path):
    assert main.main(["--mock", "--scenario", "stuck", "--output", str(tmp_path)]) == 1


def test_source_archive_excludes_local_data_and_can_run_after_extraction(tmp_path):
    archive_path = build_archive("测试源码包", tmp_path)
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert not any(
            part in {".git", ".venv", "runs", "__pycache__", ".env"}
            for name in names
            for part in Path(name).parts
        )
        assert any(name.endswith("/.env.example") for name in names)
        for required in (
            "start.bat",
            "start.py",
            "web/index.html",
            "web/assets/app.js",
            "web/assets/graph-view.js",
            "tests/graph_view.test.cjs",
        ):
            assert f"测试源码包/{required}" in names
        archive.extractall(tmp_path / "extract")
    extracted = tmp_path / "extract" / "测试源码包"
    process = subprocess.run(
        [sys.executable, "-X", "utf8", "main.py", "--mock"],
        cwd=extracted,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert process.returncode == 0, process.stderr
    assert archive_path.stat().st_size > 0


def test_packaging_refuses_path_names_and_overwrites(tmp_path):
    with pytest.raises(ValueError):
        build_archive("../escape", tmp_path)
    build_archive("once", tmp_path)
    with pytest.raises(FileExistsError):
        build_archive("once", tmp_path)
