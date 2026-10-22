"""练习：先用固定返回值实现接口，再逐个替换成真实模型调用。"""


def coder(requirement: str) -> str:
    """输入编程需求，返回完整代码。"""
    raise NotImplementedError("练习 2：先返回一段固定代码")


def reviewer(requirement: str, code: str) -> list[str]:
    """同时查看原始需求与当前代码，返回问题列表。"""
    raise NotImplementedError("练习 2：先返回教学样例的问题列表")


def fixer(requirement: str, code: str, issues: list[str]) -> str:
    """根据需求和审查问题，返回修复后的完整代码。"""
    raise NotImplementedError("练习 2：先返回教学样例的修复代码")
