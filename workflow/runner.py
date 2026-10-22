"""流程编排：编码一次，按当前版本验证、审查，并在上限内修复。"""

import logging
from collections.abc import Callable

from .agents import CodingAgent, FixAgent, ReviewAgent
from .errors import WorkflowError
from .llm import Model
from .state import Event, WorkflowState, timestamp
from .tools import CodeValidator, code_hash

logger = logging.getLogger(__name__)
Observer = Callable[[WorkflowState, Event], None]


class Workflow:
    def __init__(
        self, model: Model, validator: CodeValidator | None = None, output_retries: int = 1
    ) -> None:
        self.model = model
        self.coder = CodingAgent(model, output_retries)
        self.reviewer = ReviewAgent(model, output_retries)
        self.fixer = FixAgent(model, output_retries)
        self.validator = validator or CodeValidator()

    def run(self, state: WorkflowState, on_event: Observer | None = None) -> WorkflowState:
        if state.status != "pending" or state.code_version != 0:
            raise ValueError("每次运行必须创建新的 WorkflowState")
        if not 0 <= state.max_repairs <= 10:
            raise ValueError("max_repairs 必须在 0 至 10 之间")
        state.started_at = timestamp()
        state.model_name = self.model.name
        state.usage = self.model.usage

        def emit(stage: str, message: str, notify: bool = True) -> Event:
            event = Event(
                timestamp(),
                stage,
                state.status,
                state.code_version,
                state.repair_count,
                message,
            )
            state.history.append(event)
            logger.info("[%s] v%s %s", stage, state.code_version, message)
            if notify and on_event:
                on_event(state, event)
            return event

        def finish(status: str, message: str) -> WorkflowState:
            state.status = status
            state.finished_at = timestamp()
            emit("end", message)
            return state

        try:
            state.status = "running"
            emit("start", f"开始任务：{state.task.id}")
            result = self.coder.run(state.task)
            state.code = result.code
            state.code_version = 1
            emit("coder", result.summary)

            while True:
                state.validation = self.validator.validate(
                    state.task, state.code, state.code_version
                )
                # 防止替换验证器后意外使用旧版本的检查结论。
                if (
                    state.validation.code_version != state.code_version
                    or state.validation.code_hash != code_hash(state.code)
                ):
                    raise WorkflowError("验证结果与当前代码版本不匹配")
                emit("validate", state.validation.details)

                state.review = self.reviewer.run(
                    state.task, state.code, state.code_version, state.validation
                )
                emit("reviewer", f"{state.review.summary} 问题数：{len(state.review.issues)}")

                if state.validation.passed and not state.review.issues:
                    return finish("completed", "当前版本通过验收，且审查无待处理问题")
                if state.repair_count >= state.max_repairs:
                    return finish("needs_changes", "达到修复次数上限，仍有问题需要处理")

                result = self.fixer.run(
                    state.task, state.code, state.code_version, state.review, state.validation
                )
                state.code = result.code
                state.code_version += 1
                state.repair_count += 1
                # 新代码必须重新检查，旧版本的审查意见只保留在历史快照中。
                state.review = None
                state.validation = None
                emit("fixer", result.summary)
        except Exception as exc:
            state.status = "failed"
            state.error = f"{type(exc).__name__}: {exc}"
            state.finished_at = timestamp()
            event = emit("error", state.error, notify=False)
            if on_event:
                on_event(state, event)
            return state
