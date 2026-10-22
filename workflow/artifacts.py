"""按运行保存日志、逐版本快照、最终代码和汇总报告。"""

import json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from .state import Event, WorkflowState, timestamp


def write_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class RunStore:
    def __init__(self, output_root: Path) -> None:
        run_id = timestamp()[:19].replace("-", "").replace(":", "").replace("T", "-")
        self.path = output_root / f"{run_id}-{uuid4().hex[:8]}"
        self.path.mkdir(parents=True, exist_ok=False)
        (self.path / "versions").mkdir()
        (self.path / "snapshots").mkdir()

    def record(self, state: WorkflowState, event: Event) -> None:
        snapshot = state.to_dict()
        number = len(state.history)
        write_json(self.path / "snapshots" / f"{number:03d}-{event.stage}.json", snapshot)
        write_json(self.path / "report.json", snapshot)
        if state.code_version:
            version = self.path / "versions" / f"v{state.code_version:03d}.py"
            if not version.exists():
                version.write_text(state.code, encoding="utf-8")
            if state.code_version == 1:
                (self.path / "initial.py").write_text(state.code, encoding="utf-8")
            (self.path / "final.py").write_text(state.code, encoding="utf-8")
        with (self.path / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")

    def finish(self, state: WorkflowState) -> None:
        write_json(self.path / "report.json", state.to_dict())
        lines = [
            "# 代码审查执行报告",
            "",
            f"- 任务：{state.task.id}",
            f"- 模型：{state.model_name}",
            f"- 状态：{state.status}",
            f"- 当前代码版本：{state.code_version}",
            f"- 修复次数：{state.repair_count}/{state.max_repairs}",
            f"- 开始时间：{state.started_at}",
            f"- 结束时间：{state.finished_at}",
            f"- 请求次数：{state.usage.requests}；网络重试：{state.usage.retries}",
            f"- 输入/输出 Token：{state.usage.prompt_tokens}/{state.usage.completion_tokens}",
            "",
            "## 原始需求",
            "",
            state.task.requirement,
        ]
        if state.validation:
            lines.extend(["", "## 当前验证", "", state.validation.details])
            for case in state.validation.cases:
                label = "通过" if case["passed"] else "失败"
                lines.append(f"- {case['name']}：{label}。{case['detail']}")
        if state.review:
            lines.extend(["", "## 当前审查", "", state.review.summary])
            for issue in state.review.issues:
                location = f"第 {issue.line} 行" if issue.line else "未定位到具体行"
                lines.extend(
                    [
                        "",
                        f"- [{issue.severity}] {location}：{issue.message}",
                        f"  证据：{issue.evidence}",
                        f"  建议：{issue.suggestion}",
                    ]
                )
        if state.error:
            lines.extend(["", "## 执行错误", "", state.error])
        if state.workflow:
            lines.extend(
                [
                    "",
                    "## 流程快照",
                    "",
                    f"流程：{state.workflow['name']}。完整配置见 workflow.json，"
                    "节点输出见 report.json 的 node_runs。",
                ]
            )
        verifications = [
            run for run in state.node_runs if run["kind"] == "verifier" and run.get("output")
        ]
        if verifications:
            lines.extend(
                [
                    "",
                    "## 候选问题的独立验证",
                    "",
                    "审查意见是候选问题；被驳回的候选不进入修复，待确认的问题不能据此宣称通过。",
                ]
            )
            for run in verifications:
                lines.append(f"\n### v{run['code_version']}\n\n{run['output']['summary']}")
                for finding in run["output"]["findings"]:
                    lines.append(f"- {finding['id']} [{finding['verdict']}] {finding['reason']}")
        lines.extend(["", "## 执行步骤", ""])
        lines.extend(
            f"- {event.time} [{event.stage}] v{event.code_version}：{event.message}"
            for event in state.history
        )
        lines.extend(
            [
                "",
                "## 结果范围",
                "",
                "通过表示当前版本满足已提供的验收用例，且本轮审查没有待处理问题，不能证明程序对所有输入完全正确。",
                "final.py 是本次最后生成的候选代码；是否通过必须以 status 为准。",
                "",
            ]
        )
        (self.path / "report.md").write_text("\n".join(lines), encoding="utf-8")
