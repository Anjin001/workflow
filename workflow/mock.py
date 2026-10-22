"""离线回归与演示专用模型；不把固定结果冒充为真实模型能力。"""

import json
from pathlib import Path

from .state import ModelUsage
from .task import TaskSpec, load_task

FIXTURES = {
    "average": (
        """def average(numbers):
    return sum(numbers) / len(numbers)
""",
        """def average(numbers):
    if not numbers:
        return 0
    return sum(numbers) / len(numbers)
""",
    ),
    "deduplicate": (
        "def deduplicate(items):\n    return sorted(set(items))\n",
        "def deduplicate(items):\n    return list(dict.fromkeys(items))\n",
    ),
    "factorial": (
        """def factorial(n):
    result = 1
    for value in range(1, n):
        result *= value
    return result
""",
        """def factorial(n):
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError('n must be an integer')
    if n < 0:
        raise ValueError('n must be non-negative')
    result = 1
    for value in range(2, n + 1):
        result *= value
    return result
""",
    ),
}


class MockModel:
    def __init__(self, task: TaskSpec, scenario: str = "repair") -> None:
        if scenario not in {"repair", "pass", "stuck"}:
            raise ValueError("未知离线场景")
        if task.id not in FIXTURES:
            raise ValueError("离线模型仅支持 examples 中提供的三个固定任务")
        original = load_task(
            Path(__file__).resolve().parent.parent / "examples" / f"{task.id}.json"
        )
        if original.to_dict() != task.to_dict():
            raise ValueError("离线模型不能用于修改后的示例或自定义任务，请使用真实模型")
        self.name = f"mock:{scenario}"
        self.usage = ModelUsage()
        self.task_id = task.id
        self.scenario = scenario

    def complete(self, role: str, messages: list[dict[str, str]]) -> str:
        self.usage.requests += 1
        payload = json.loads(messages[1]["content"])
        buggy, fixed = FIXTURES[self.task_id]
        if role == "coder":
            result = {
                "code": fixed if self.scenario == "pass" else buggy,
                "summary": "离线编码：返回固定样例实现。",
            }
        elif role == "fixer":
            result = {
                "code": buggy if self.scenario == "stuck" else fixed,
                "summary": "离线修复：根据预设场景返回候选版本。",
            }
        elif role == "reviewer":
            validation = payload["validation"]
            failed = [case for case in validation["cases"] if not case["passed"]]
            evidence = failed[0]["detail"] if failed else validation["details"]
            issues = (
                []
                if validation["passed"]
                else [
                    {
                        "severity": "medium",
                        "line": None,
                        "message": "当前实现未满足固定验收。",
                        "evidence": evidence,
                        "suggestion": "对照原始需求修正边界或业务逻辑，保留函数接口。",
                    }
                ]
            )
            result = {"summary": "离线审查：依据实际验收结果生成固定格式意见。", "issues": issues}
        elif role == "custom":
            result = {
                "summary": "离线角色占位输出；未执行自定义提示词推理。",
                "recommendations": ["切换真实模型后，此节点将按你配置的职责分析所选输入。"],
            }
        elif role == "verifier":
            result = {
                "summary": "离线验证仅展示结构，候选问题来自真实验收失败。",
                "findings": [
                    {
                        "id": item["id"],
                        "verdict": "confirmed"
                        if not payload["validation"]["passed"]
                        else "uncertain",
                        "reason": "固定演示结论：依据传入的验收失败记录，未执行独立模型推理。",
                        "source_quote": payload["code"].splitlines()[0],
                    }
                    for item in payload["candidates"]
                ],
            }
        else:
            raise ValueError(f"未知角色：{role}")
        return json.dumps(result, ensure_ascii=False)

    def close(self) -> None:
        pass
