"""命令行入口：加载任务与配置，启动 Workflow，保存报告。"""

import argparse
import logging
import sys
from pathlib import Path

from workflow.artifacts import RunStore, write_json
from workflow.config import Settings
from workflow.errors import WorkflowError
from workflow.llm import ChatModel
from workflow.mock import MockModel
from workflow.runner import Workflow
from workflow.state import WorkflowState
from workflow.task import load_task
from workflow.tools import CodeValidator

ROOT = Path(__file__).resolve().parent


def parser() -> argparse.ArgumentParser:
    arguments = argparse.ArgumentParser(description="Homework 2：多 Agent 代码审查流程")
    arguments.add_argument("--task", type=Path, default=ROOT / "examples" / "average.json")
    arguments.add_argument("--mock", action="store_true", help="使用固定样例离线运行，不调用 API")
    arguments.add_argument(
        "--scenario",
        choices=["repair", "pass", "stuck"],
        default=None,
        help="仅 --mock 可用；默认 repair",
    )
    arguments.add_argument("--max-repairs", type=int, default=2)
    arguments.add_argument("--output", type=Path, default=ROOT / "runs")
    return arguments


def main(argv: list[str] | None = None) -> int:
    arguments = parser()
    args = arguments.parse_args(argv)
    if not 0 <= args.max_repairs <= 10:
        arguments.error("--max-repairs 必须在 0 至 10 之间")
    if args.scenario and not args.mock:
        arguments.error("--scenario 只能与 --mock 一起使用")
    model = None
    handler = None
    logger = logging.getLogger("workflow")
    logger.setLevel(logging.INFO)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console)
    try:
        task = load_task(args.task)
        settings = Settings.load(ROOT)
        model = MockModel(task, args.scenario or "repair") if args.mock else ChatModel(settings)
        store = RunStore(args.output)
        handler = logging.FileHandler(store.path / "run.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
        write_json(store.path / "task.json", task.to_dict())
        if args.mock:
            logger.info("离线固定样例；未调用真实模型，验收仍实际执行。")
        state = WorkflowState(task=task, max_repairs=args.max_repairs)
        workflow = Workflow(model, CodeValidator(settings.test_timeout), settings.output_retries)
        result = workflow.run(state, on_event=store.record)
        store.finish(result)
        print(f"\n状态：{result.status}；修复：{result.repair_count}/{result.max_repairs}")
        print(f"报告：{store.path / 'report.md'}")
        return {"completed": 0, "needs_changes": 1, "failed": 2}[result.status]
    except (OSError, ValueError, WorkflowError) as exc:
        print(f"运行失败：{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("运行已由用户中断，已完成步骤的快照保留在输出目录。", file=sys.stderr)
        return 130
    finally:
        if model:
            model.close()
        if handler:
            logger.removeHandler(handler)
            handler.close()
        logger.removeHandler(console)
        console.close()


if __name__ == "__main__":
    raise SystemExit(main())
