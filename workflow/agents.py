"""三个角色的输入输出边界。Agent 做具体任务，不决定整个流程如何走。"""
from dataclasses import asdict

from .llm import ModelClient
from .prompts import CODER_PROMPT, FIXER_PROMPT, REVIEWER_PROMPT
from .state import ValidationResult


def _read_code(result: dict) -> str:
    code = result.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("模型输出缺少非空字符串 code")
    return code


def coder(requirement: str, model: ModelClient) -> str:
    """需求 -> 代码。"""
    result = model.generate("coder", CODER_PROMPT, {"requirement": requirement})
    return _read_code(result)


def reviewer(
    requirement: str, code: str, validation: ValidationResult, model: ModelClient
) -> list[str]:
    """需求 + 当前代码 + 当前验证结果 -> 问题列表。"""
    result = model.generate("reviewer", REVIEWER_PROMPT, {
        "requirement": requirement,
        "code": code,
        "validation": asdict(validation),
    })
    issues = result.get("issues")
    if not isinstance(issues, list) or any(
        not isinstance(issue, str) or not issue.strip() for issue in issues
    ):
        raise ValueError("模型输出的 issues 必须是非空问题字符串组成的列表，或空列表")
    return issues


def fixer(
    requirement: str,
    code: str,
    issues: list[str],
    validation: ValidationResult,
    model: ModelClient,
) -> str:
    """需求 + 代码 + 审查意见 + 验证结果 -> 修复后的代码。"""
    result = model.generate("fixer", FIXER_PROMPT, {
        "requirement": requirement,
        "code": code,
        "issues": issues,
        "validation": asdict(validation),
    })
    return _read_code(result)
