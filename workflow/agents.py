"""独立的编码、审查、修复角色，共用模型接口与输出校验机制。"""

import json
import logging
from collections.abc import Callable
from dataclasses import asdict
from typing import Any, TypeVar

from .errors import OutputError
from .llm import Model
from .prompts import CODER_PROMPT, FIXER_PROMPT, REVIEWER_PROMPT
from .state import CodeResult, Issue, ReviewResult, ValidationResult
from .task import TaskSpec, reject_constant, text

logger = logging.getLogger(__name__)
Result = TypeVar("Result")


def object_fields(data: Any, names: set[str]) -> dict:
    if not isinstance(data, dict) or set(data) != names:
        raise ValueError(f"JSON 对象必须且只能包含字段：{', '.join(sorted(names))}")
    return data


def parse_code(data: Any) -> CodeResult:
    data = object_fields(data, {"code", "summary"})
    return CodeResult(
        text(data["code"], "code", 64_000) + "\n", text(data["summary"], "summary", 2000)
    )


def parse_review(data: Any, line_count: int) -> ReviewResult:
    data = object_fields(data, {"summary", "issues"})
    raw_issues = data["issues"]
    if not isinstance(raw_issues, list) or len(raw_issues) > 30:
        raise ValueError("issues 必须是最多 30 项的问题列表")
    issues = []
    for item in raw_issues:
        item = object_fields(item, {"severity", "line", "message", "evidence", "suggestion"})
        if item["severity"] not in {"high", "medium", "low"}:
            raise ValueError("severity 必须为 high、medium 或 low")
        line = item["line"]
        if line is not None and (type(line) is not int or not 1 <= line <= line_count):
            raise ValueError("line 必须是当前源码中的有效行号，或 null")
        issues.append(
            Issue(
                severity=item["severity"],
                line=line,
                message=text(item["message"], "message", 2000),
                evidence=text(item["evidence"], "evidence", 3000),
                suggestion=text(item["suggestion"], "suggestion", 3000),
            )
        )
    return ReviewResult(text(data["summary"], "summary", 2000), issues)


class JsonAgent:
    """负责一次角色任务；输出不合规时带反馈重试，业务修复由 Workflow 控制。"""

    def __init__(self, model: Model, role: str, prompt: str, output_retries: int = 1) -> None:
        self.model = model
        self.role = role
        self.prompt = prompt
        self.output_retries = output_retries

    def ask(self, payload: dict, parse: Callable[[Any], Result]) -> Result:
        messages = [
            {"role": "system", "content": self.prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        for attempt in range(self.output_retries + 1):
            raw = self.model.complete(self.role, messages)
            try:
                if len(raw) > 100_000:
                    raise ValueError("模型 JSON 输出超过 100000 字符")
                return parse(json.loads(raw, parse_constant=reject_constant))
            except (ValueError, TypeError) as exc:
                if attempt == self.output_retries:
                    raise OutputError(f"{self.role} 输出不合规：{exc}") from exc
                logger.warning("%s 输出格式不合规，正在请求重新输出", self.role)
                messages.extend(
                    [
                        {"role": "assistant", "content": raw[:100_000]},
                        {
                            "role": "user",
                            "content": f"格式校验失败：{exc}。请按系统约定重新输出完整 JSON。",
                        },
                    ]
                )
        raise OutputError(f"{self.role} 未返回有效结果")


class CodingAgent(JsonAgent):
    def __init__(self, model: Model, output_retries: int = 1) -> None:
        super().__init__(model, "coder", CODER_PROMPT, output_retries)

    def run(self, task: TaskSpec) -> CodeResult:
        return self.ask({"task": task.to_dict()}, parse_code)


class ReviewAgent(JsonAgent):
    def __init__(self, model: Model, output_retries: int = 1) -> None:
        super().__init__(model, "reviewer", REVIEWER_PROMPT, output_retries)

    def run(
        self, task: TaskSpec, code: str, version: int, validation: ValidationResult
    ) -> ReviewResult:
        return self.ask(
            {
                "task": task.to_dict(),
                "code": code,
                "code_version": version,
                "validation": asdict(validation),
            },
            lambda data: parse_review(data, len(code.splitlines())),
        )


class FixAgent(JsonAgent):
    def __init__(self, model: Model, output_retries: int = 1) -> None:
        super().__init__(model, "fixer", FIXER_PROMPT, output_retries)

    def run(
        self,
        task: TaskSpec,
        code: str,
        version: int,
        review: ReviewResult,
        validation: ValidationResult,
    ) -> CodeResult:
        return self.ask(
            {
                "task": task.to_dict(),
                "code": code,
                "code_version": version,
                "review": asdict(review),
                "validation": asdict(validation),
            },
            parse_code,
        )
