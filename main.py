"""命令行入口：读参数、创建对象、启动流程、保存输出。"""
import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from workflow.llm import DEMO_REQUIREMENT, DemoModel, ModelClient
from workflow.runner import run_workflow
from workflow.state import WorkflowState


def main() -> int:
    parser = argparse.ArgumentParser(description="代码审查 Workflow：可运行的学习模板")
    parser.add_argument("--mode", choices=["demo", "real"], default="demo")
    parser.add_argument("--scenario", choices=["repair", "pass", "stuck"], default="repair")
    parser.add_argument("--requirement", default=DEMO_REQUIREMENT)
    parser.add_argument("--max-repairs", type=int, default=2)
    args = parser.parse_args()
    if args.max_repairs < 0:
        parser.error("--max-repairs 不能小于 0")
    if args.mode == "demo" and args.requirement != DEMO_REQUIREMENT:
        parser.error("demo 仅支持内置平均值样例；自定义需求需先接入真实模型和对应验收用例")

    # 同一个 model 实例可以服务三个角色；角色提示词与输入数据各不相同。
    if args.mode == "demo":
        print("固定样例演示：未调用真实模型。验收工具会实际运行平均值测试。")
        model = DemoModel(scenario=args.scenario)
    else:
        print("真实模型接入练习：请先实现 workflow/llm.py 中的 ModelClient.generate。")
        model = ModelClient()

    state = WorkflowState(requirement=args.requirement, max_repairs=args.max_repairs)
    result = run_workflow(state, model, on_event=print)

    # 每次运行使用单独目录，保留初版、最终版和完整状态记录。
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6]
    output = Path(__file__).resolve().parent / "runs" / run_id
    output.mkdir(parents=True, exist_ok=False)
    if result.code_version:
        original = next(item["code"] for item in result.history if item["stage"] == "coder")
        (output / "initial.py").write_text(original, encoding="utf-8")
        (output / "final.py").write_text(result.code, encoding="utf-8")
    (output / "report.json").write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n最终状态：{result.status}；修复次数：{result.repair_count}")
    print(f"运行记录：{output}")
    return {"completed": 0, "needs_changes": 1, "failed": 2}[result.status]


if __name__ == "__main__":
    raise SystemExit(main())
