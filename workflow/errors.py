"""可预期的配置、模型和数据错误。"""


class WorkflowError(Exception):
    """可以直接向用户说明原因的运行错误。"""


class ModelError(WorkflowError):
    """模型服务请求失败。"""


class OutputError(WorkflowError):
    """模型输出未满足约定的数据结构。"""


class WorkflowCancelled(WorkflowError):
    """用户要求在步骤边界停止任务。"""
