"""共享状态：整个任务的记录本，Workflow 负责更新它。"""
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    code_version: int
    passed: bool
    details: str


@dataclass
class WorkflowState:
    requirement: str
    code: str = ""
    code_version: int = 0
    issues: list[str] = field(default_factory=list)
    validation: ValidationResult | None = None
    repair_count: int = 0
    max_repairs: int = 2
    # pending / running / completed / needs_changes / failed
    status: str = "pending"
    error: str = ""
    history: list[dict] = field(default_factory=list)
