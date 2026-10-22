"""项目入口：目前仅展示任务状态，真实 Workflow 将在练习中接入。"""
import argparse
import json
from dataclasses import asdict

from workflow.state import WorkflowState


def main() -> None:
    parser = argparse.ArgumentParser(description="Homework 2：代码审查 Workflow 学习骨架")
    parser.add_argument(
        "--requirement",
        default="实现 average(numbers)，空列表返回 0",
        help="要完成的编程需求",
    )
    args = parser.parse_args()
    state = WorkflowState(requirement=args.requirement)
    print("项目初始化成功。目前只展示任务状态，尚未调用 Agent。")
    print(json.dumps(asdict(state), ensure_ascii=False, indent=2))
    print("下一步：按照 LEARNING.md 实现三个固定返回值的 Agent。")


if __name__ == "__main__":
    main()
