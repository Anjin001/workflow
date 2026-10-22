"""先读此文件：外层 Workflow 怎样调用 Agent、传数据、决定下一步。"""
from dataclasses import asdict
from typing import Callable

from .agents import coder, fixer, reviewer
from .llm import ModelClient
from .state import WorkflowState
from .tools import validate_code


def run_workflow(
    state: WorkflowState,
    model: ModelClient,
    on_event: Callable[[str], None] | None = None,
) -> WorkflowState:
    """一次调用处理一个新任务。on_event 让入口程序决定怎样显示进度。"""
    if state.status != "pending" or state.code_version != 0:
        raise ValueError("请为每次运行创建新的 WorkflowState")
    if state.max_repairs < 0:
        raise ValueError("最大修复次数不能小于 0")

    def record(stage: str, message: str) -> None:
        # 存当前值的副本，保证后续修复不会覆盖历史记录。
        state.history.append({
            "stage": stage,
            "message": message,
            "code_version": state.code_version,
            "repair_count": state.repair_count,
            "code": state.code,
            "issues": list(state.issues),
            "validation": asdict(state.validation) if state.validation else None,
        })
        if on_event:
            on_event(f"[{stage}] {message}")

    try:
        state.status = "running"

        # 1. 编码只执行一次，后续由修复 Agent 处理已有代码。
        state.code = coder(state.requirement, model)
        state.code_version = 1
        record("coder", "已生成第 1 版代码")

        while True:
            # 2. 每轮都重新检查当前代码，再把证据交给审查 Agent。
            state.validation = validate_code(state.code, state.code_version)
            record("validate", "验收通过" if state.validation.passed else "验收未通过")
            state.issues = reviewer(state.requirement, state.code, state.validation, model)
            record("reviewer", f"审查发现 {len(state.issues)} 个问题")

            # 3. 模型认为没问题还不够，固定验收也必须通过。
            if not state.issues and state.validation.passed:
                state.status = "completed"
                record("end", "当前代码通过验收，且审查未提出待处理问题")
                return state

            # 4. 有限次数循环：0 次表示只编码和检查，不执行修复。
            if state.repair_count >= state.max_repairs:
                state.status = "needs_changes"
                record("end", "达到修复次数上限，仍有待处理问题")
                return state

            # 5. 把原始需求、当前代码和问题一起交给修复 Agent。
            state.code = fixer(
                state.requirement, state.code, state.issues, state.validation, model
            )
            state.repair_count += 1
            state.code_version += 1
            # 新代码不能沿用旧版本的结论，下一轮重新验证和审查。
            state.issues = []
            state.validation = None
            record("fixer", f"第 {state.repair_count} 次修复，生成第 {state.code_version} 版代码")

    except Exception as exc:
        # 异常是执行失败，不能伪装成审查通过。
        state.status = "failed"
        state.error = f"{type(exc).__name__}: {exc}"
        record("error", state.error)
        return state
