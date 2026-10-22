"""结构化的角色结果、验证结果和共享状态。"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from .task import TaskSpec


def timestamp() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class CodeResult:
    code: str
    summary: str


@dataclass(frozen=True)
class Issue:
    severity: Literal["high", "medium", "low"]
    line: int | None
    message: str
    evidence: str
    suggestion: str


@dataclass(frozen=True)
class ReviewResult:
    summary: str
    issues: list[Issue]


@dataclass(frozen=True)
class ValidationResult:
    code_version: int
    code_hash: str
    passed: bool
    details: str
    cases: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ModelUsage:
    requests: int = 0
    retries: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class Event:
    time: str
    stage: str
    status: str
    code_version: int
    repair_count: int
    message: str


@dataclass
class WorkflowState:
    task: TaskSpec
    max_repairs: int = 2
    code: str = ""
    code_version: int = 0
    review: ReviewResult | None = None
    validation: ValidationResult | None = None
    repair_count: int = 0
    status: str = "pending"
    error: str = ""
    model_name: str = ""
    started_at: str = ""
    finished_at: str = ""
    usage: ModelUsage = field(default_factory=ModelUsage)
    history: list[Event] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["task"] = self.task.to_dict()
        return data
