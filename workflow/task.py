"""任务文件解析；验收用例由用户提供，Agent 无权修改。"""

import json
import keyword
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ALLOWED_EXCEPTIONS = {
    "ValueError",
    "TypeError",
    "ZeroDivisionError",
    "IndexError",
    "KeyError",
    "OverflowError",
}


def text(value: Any, field: str, limit: int = 10_000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{field} 必须是长度为 1 至 {limit} 的非空字符串")
    return value.strip()


def reject_constant(value: str) -> None:
    raise ValueError(f"JSON 中不允许 {value}")


@dataclass(frozen=True)
class TestCase:
    name: str
    args: list[Any]
    kwargs: dict[str, Any]
    expected: Any = None
    raises: str | None = None
    tolerance: float = 0.0
    check_input_unchanged: bool = False

    def to_dict(self) -> dict:
        result = asdict(self)
        result.pop("expected" if self.raises else "raises")
        return result


@dataclass(frozen=True)
class TaskSpec:
    id: str
    requirement: str
    function_name: str
    cases: list[TestCase]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "requirement": self.requirement,
            "function_name": self.function_name,
            "cases": [case.to_dict() for case in self.cases],
        }

    @classmethod
    def from_dict(cls, data: Any) -> "TaskSpec":
        if not isinstance(data, dict):
            raise ValueError("任务文件根节点必须是 JSON 对象")
        task_id = text(data.get("id"), "id", 80)
        requirement = text(data.get("requirement"), "requirement")
        function_name = text(data.get("function_name"), "function_name", 80)
        if not function_name.isidentifier() or keyword.iskeyword(function_name):
            raise ValueError("function_name 必须是合法 Python 函数名")
        raw_cases = data.get("cases")
        if not isinstance(raw_cases, list) or not 1 <= len(raw_cases) <= 100:
            raise ValueError("cases 必须包含 1 至 100 个验收用例")
        cases = []
        for index, item in enumerate(raw_cases, 1):
            if not isinstance(item, dict):
                raise ValueError(f"第 {index} 个用例必须是对象")
            name = text(item.get("name"), f"cases[{index}].name", 120)
            args = item.get("args", [])
            kwargs = item.get("kwargs", {})
            if not isinstance(args, list) or not isinstance(kwargs, dict):
                raise ValueError(f"用例 {name} 的 args/kwargs 必须为数组/对象")
            if any(not key.isidentifier() or keyword.iskeyword(key) for key in kwargs):
                raise ValueError(f"用例 {name} 包含非法关键字参数")
            if ("expected" in item) == ("raises" in item):
                raise ValueError(f"用例 {name} 必须且只能指定 expected 或 raises")
            raises = item.get("raises")
            if "raises" in item and (
                not isinstance(raises, str) or raises not in ALLOWED_EXCEPTIONS
            ):
                raise ValueError(f"用例 {name} 使用了不支持的异常类型")
            tolerance = item.get("tolerance", 0.0)
            if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or tolerance < 0:
                raise ValueError(f"用例 {name} 的 tolerance 必须是非负有限数")
            check_input = item.get("check_input_unchanged", False)
            if type(check_input) is not bool:
                raise ValueError(f"用例 {name} 的 check_input_unchanged 必须是布尔值")
            cases.append(
                TestCase(name, args, kwargs, item.get("expected"), raises, tolerance, check_input)
            )
        if len({case.name for case in cases}) != len(cases):
            raise ValueError("验收用例名称不能重复")
        return cls(task_id, requirement, function_name, cases)


def load_task(path: Path) -> TaskSpec:
    if path.stat().st_size > 256_000:
        raise ValueError("任务文件不能超过 256 KB")
    data = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=reject_constant)
    return TaskSpec.from_dict(data)
