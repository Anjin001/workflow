"""Workflow 的共享任务状态。"""
from dataclasses import dataclass, field


@dataclass
class WorkflowState:
    requirement: str
    code: str = ""
    issues: list[str] = field(default_factory=list)
    repair_count: int = 0
    max_repairs: int = 2
    status: str = "pending"
