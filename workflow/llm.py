"""模型接入点。DemoModel 使用固定数据，不调用任何真实大模型。"""

DEMO_REQUIREMENT = "实现 average(numbers)，计算数值列表平均值，空列表返回 0"

BUGGY_CODE = """def average(numbers):
    return sum(numbers) / len(numbers)
"""

FIXED_CODE = """def average(numbers):
    if not numbers:
        return 0
    return sum(numbers) / len(numbers)
"""


class ModelClient:
    """三个 Agent 都依赖这个接口，可以共用同一个模型客户端。"""

    def generate(self, role: str, system_prompt: str, payload: dict) -> dict:
        """输入角色、提示词和任务数据，返回已经解析为字典的模型结果。

        下一阶段在这里接入作业一的模型调用：
        1. 把 system_prompt 放入 SystemMessage。
        2. 用 json.dumps(payload) 构造 HumanMessage。
        3. 调用模型并解析 JSON，处理超时、重试和格式错误。
        4. 需要工具时，在此处或独立 Agent 类中接入作业一的工具循环。

        普通模型请求也能作为 Workflow 节点；完整 Agent 的工具循环需要另行接入。
        """
        raise NotImplementedError("真实模型尚未接入，请阅读 workflow/llm.py 的说明")


class DemoModel(ModelClient):
    """固定的平均值函数演示，用于观察流程，不能处理任意编程需求。

    repair：初始代码有错误，修复后通过。
    pass：初始代码直接通过。
    stuck：每次修复仍返回错误代码，演示终止上限。
    """

    def __init__(self, scenario: str = "repair") -> None:
        if scenario not in {"repair", "pass", "stuck"}:
            raise ValueError("未知演示场景")
        self.scenario = scenario

    def generate(self, role: str, system_prompt: str, payload: dict) -> dict:
        # 这里按角色返回固定结果。真实模型会读取提示词和任务数据进行处理。
        if role == "coder":
            return {"code": FIXED_CODE if self.scenario == "pass" else BUGGY_CODE}
        if role == "reviewer":
            issues = []
            if not payload["validation"]["passed"]:
                issues = ["固定演示审查：空列表未得到要求的结果，请检查空列表分支。"]
            return {"issues": issues}
        if role == "fixer":
            return {"code": BUGGY_CODE if self.scenario == "stuck" else FIXED_CODE}
        raise ValueError(f"未知角色：{role}")
