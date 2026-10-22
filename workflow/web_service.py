"""本地网页的后台任务管理；每次仅执行一个工作流。"""

import json
import logging
import re
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .artifacts import RunStore, write_json
from .config import Settings
from .errors import WorkflowCancelled
from .graph import default_graph, parse_graph
from .graph_runner import GraphWorkflow
from .llm import ChatModel, Model
from .mock import MockModel
from .state import Event, WorkflowState, timestamp
from .task import TaskSpec
from .tools import CodeValidator

RUN_ID = re.compile(r"[A-Za-z0-9-]{1,80}\Z")
logger = logging.getLogger(__name__)


@dataclass
class Job:
    store: RunStore
    cancel: threading.Event
    future: Future | None = None


class CancelAwareModel:
    """网络请求不能强行杀线程，在请求前后检查停止信号。"""

    def __init__(self, model: Model, cancel: threading.Event) -> None:
        self.model = model
        self.name = model.name
        self.usage = model.usage
        self.cancel = cancel

    def complete(self, role: str, messages: list[dict[str, str]]) -> str:
        self.check()
        result = self.model.complete(role, messages)
        self.check()
        return result

    def check(self) -> None:
        if self.cancel.is_set():
            raise WorkflowCancelled()


class JobManager:
    def __init__(self, output_root: Path, model_factory: Callable[[Settings], Model] = ChatModel):
        self.output_root = output_root
        self.model_factory = model_factory
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="workflow")
        # Windows 不允许读取中的文件被替换；读写共用锁保证快照一致。
        self.lock = threading.RLock()
        self.jobs: dict[str, Job] = {}
        self.active: str | None = None

    def submit(
        self,
        task: TaskSpec,
        settings: Settings,
        mode: str,
        scenario: str,
        max_repairs: int,
        definition: dict | None = None,
    ) -> str:
        graph = parse_graph(definition) if definition is not None else default_graph()
        if mode == "mock":
            MockModel(task, scenario)  # 提交之前检查是否是支持的离线任务。
        with self.lock:
            if self.active:
                raise RuntimeError("已有任务正在运行，请等待完成或先停止它")
            store = RunStore(self.output_root)
            write_json(store.path / "task.json", task.to_dict())
            initial = WorkflowState(task, max_repairs, workflow=graph.model_dump())
            write_json(store.path / "workflow.json", graph.model_dump())
            write_json(store.path / "report.json", initial.to_dict())
            run_id = store.path.name
            job = Job(store, threading.Event())
            self.jobs[run_id] = job
            self.active = run_id
            job.future = self.executor.submit(
                self._execute,
                run_id,
                task,
                settings,
                mode,
                scenario,
                max_repairs,
                graph.model_dump(),
            )
        return run_id

    def _execute(
        self,
        run_id: str,
        task: TaskSpec,
        settings: Settings,
        mode: str,
        scenario: str,
        max_repairs: int,
        definition: dict,
    ) -> None:
        job = self.jobs[run_id]
        state = WorkflowState(task, max_repairs, workflow=definition)
        model = None
        handler = None
        workflow_logger = logging.getLogger("workflow")
        workflow_logger.setLevel(logging.INFO)
        try:
            handler = logging.FileHandler(job.store.path / "run.log", encoding="utf-8")
            thread_id = threading.get_ident()
            handler.addFilter(lambda record: record.thread == thread_id)
            handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
            workflow_logger.addHandler(handler)
            model = MockModel(task, scenario) if mode == "mock" else self.model_factory(settings)
            wrapped = CancelAwareModel(model, job.cancel)

            def observe(current: WorkflowState, event: Event) -> None:
                if current.status == "running":
                    wrapped.check()
                with self.lock:
                    job.store.record(current, event)

            state = GraphWorkflow(
                wrapped,
                parse_graph(definition),
                CodeValidator(settings.test_timeout),
                settings.output_retries,
            ).run(state, observe)
        except Exception as exc:
            state.status = "failed"
            state.error = (
                str(exc).replace(settings.api_key, "[已隐藏]") if settings.api_key else str(exc)
            )
            state.finished_at = timestamp()
            event = Event(
                timestamp(),
                "error",
                state.status,
                state.code_version,
                state.repair_count,
                state.error,
            )
            state.history.append(event)
            with self.lock:
                job.store.record(state, event)
        finally:
            try:
                with self.lock:
                    job.store.finish(state)
                if model:
                    model.close()
            finally:
                if handler:
                    workflow_logger.removeHandler(handler)
                    handler.close()
                with self.lock:
                    self.active = None
                    # 完成任务只保留少量控制对象；历史记录从磁盘读取。
                    for key in list(self.jobs):
                        if len(self.jobs) <= 8:
                            break
                        if key != run_id and self.jobs[key].future and self.jobs[key].future.done():
                            del self.jobs[key]

    def directory(self, run_id: str) -> Path:
        if not RUN_ID.fullmatch(run_id):
            raise FileNotFoundError("任务不存在")
        directory = (self.output_root / run_id).resolve()
        if directory.parent != self.output_root.resolve() or not directory.is_dir():
            raise FileNotFoundError("任务不存在")
        return directory

    def detail(self, run_id: str, include_versions: bool = True) -> dict:
        with self.lock:
            return self._read_detail(run_id, include_versions)

    def _read_detail(self, run_id: str, include_versions: bool) -> dict:
        directory = self.directory(run_id)
        report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        report["run_id"] = run_id
        with self.lock:
            job = self.jobs.get(run_id)
            report["cancel_requested"] = bool(job and job.cancel.is_set())
            is_active = self.active == run_id
        if report.get("status") in {"pending", "running"} and not is_active:
            report["status"] = "interrupted"
        if include_versions:
            report["versions"] = [
                {"version": int(path.stem[1:]), "code": path.read_text(encoding="utf-8")}
                for path in sorted((directory / "versions").glob("v[0-9][0-9][0-9].py"))
            ]
            report["reviews"] = []
            for path in sorted((directory / "snapshots").glob("*-reviewer.json")):
                snapshot = json.loads(path.read_text(encoding="utf-8"))
                report["reviews"].append(
                    {
                        "version": snapshot["code_version"],
                        "review": snapshot.get("review"),
                        "validation": snapshot.get("validation"),
                    }
                )
        return report

    def history(self) -> dict:
        items = []
        if self.output_root.exists():
            for directory in sorted(self.output_root.iterdir(), reverse=True):
                if len(items) >= 50:
                    break
                if not directory.is_dir() or not RUN_ID.fullmatch(directory.name):
                    continue
                try:
                    report = self.detail(directory.name, include_versions=False)
                    task = report["task"]
                    items.append(
                        {
                            "run_id": directory.name,
                            "title": task["requirement"][:100],
                            "status": report["status"],
                            "started_at": report.get("started_at", ""),
                            "model_name": report.get("model_name", ""),
                        }
                    )
                except (OSError, ValueError, KeyError, TypeError):
                    continue
        return {"items": items, "active_run": self.active}

    def cancel(self, run_id: str) -> None:
        with self.lock:
            if self.active != run_id:
                raise ValueError("该任务已经结束")
            self.jobs[run_id].cancel.set()

    def close(self) -> None:
        with self.lock:
            for job in self.jobs.values():
                job.cancel.set()
        self.executor.shutdown(wait=True, cancel_futures=True)
