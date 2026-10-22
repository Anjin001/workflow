"""本机 Web 界面与 API；不对局域网或公网开放。"""

import io
import json
import os
import secrets
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .agents import CodingAgent
from .config import Settings
from .errors import WorkflowError
from .graph import GraphLibrary, default_graph, parse_graph
from .llm import ChatModel, Model
from .task import TaskSpec, load_task
from .web_models import ConnectionInput, PrepareInput, RunInput, SaveWorkflowInput, check_connection
from .web_service import JobManager

ROOT = Path(__file__).resolve().parent.parent
DOWNLOAD_FILES = {
    "final.py",
    "initial.py",
    "report.md",
    "report.json",
    "task.json",
    "workflow.json",
}


def create_app(
    root: Path = ROOT,
    output_root: Path | None = None,
    model_factory: Callable[[Settings], Model] = ChatModel,
    connection_checker: Callable[[Settings], dict] = check_connection,
) -> FastAPI:
    manager = JobManager(output_root or root / "runs", model_factory)
    library = GraphLibrary((output_root or root / "runs").parent / "workflows")

    @asynccontextmanager
    async def lifespan(app):
        yield
        manager.close()

    app = FastAPI(
        title="Workflow Studio", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.token = secrets.token_hex(32)
    app.state.manager = manager

    @app.middleware("http")
    async def local_access(request: Request, call_next):
        if request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return JSONResponse({"detail": "只允许本机访问"}, status_code=403)
        if request.url.path.startswith("/api/") and request.url.path != "/api/health":
            supplied = request.headers.get("x-workflow-token", "")
            origin = request.headers.get("origin")
            if (
                not secrets.compare_digest(supplied, app.state.token)
                or origin
                and origin != str(request.base_url).rstrip("/")
            ):
                return JSONResponse({"detail": "页面连接已失效，请刷新网页后重试"}, status_code=403)
            if request.method == "POST" and len(await request.body()) > 512_000:
                return JSONResponse({"detail": "请求过大，请缩小任务"}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        # 不使用默认错误中的 input 字段，它可能包含用户刚提交的密钥。
        return JSONResponse(
            {"detail": "输入格式不正确，请检查必填项、字段类型和长度"}, status_code=422
        )

    @app.exception_handler(ValueError)
    async def invalid_value(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(WorkflowError)
    async def workflow_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/", response_class=HTMLResponse)
    def index():
        html = (root / "web" / "index.html").read_text(encoding="utf-8")
        return html.replace("__CSRF_TOKEN__", app.state.token)

    @app.get("/api/health")
    def health():
        return {"app": "code-review-workflow", "pid": os.getpid()}

    @app.get("/api/bootstrap")
    def bootstrap():
        examples = [
            load_task(path).to_dict() for path in sorted((root / "examples").glob("*.json"))
        ]
        return {
            "examples": examples,
            "history": manager.history(),
            "workflow_templates": [default_graph().model_dump(), default_graph(True).model_dump()],
        }

    @app.get("/api/workflows")
    def workflows():
        return {"items": library.list()}

    @app.post("/api/workflows/validate")
    def validate_workflow(payload: dict):
        graph = parse_graph(payload)
        return {
            "definition": graph.model_dump(),
            "message": "结构有效：主路径完整、数据依赖有效，修复回路受次数与步数上限约束。",
        }

    @app.post("/api/workflows/save")
    def save_workflow(payload: SaveWorkflowInput):
        return library.save(payload.definition, payload.id)

    @app.post("/api/connection/check")
    def connection(payload: ConnectionInput):
        return connection_checker(payload.settings())

    @app.post("/api/connection/validate")
    def validate_connection(payload: ConnectionInput):
        settings = payload.settings()
        return {"base_url": settings.base_url, "model": settings.model}

    @app.post("/api/tasks/validate")
    def validate_task(payload: dict):
        return TaskSpec.from_dict(payload).to_dict()

    @app.post("/api/tasks/prepare")
    def prepare(payload: PrepareInput):
        requirement = payload.requirement.strip()
        if not requirement:
            raise ValueError("请先输入编程需求")
        model = model_factory(payload.connection.settings())
        try:
            task = CodingAgent(model).prepare(requirement)
            return {"task": task.to_dict(), "needs_confirmation": True}
        finally:
            model.close()

    @app.post("/api/runs", status_code=202)
    def submit(payload: RunInput):
        task = TaskSpec.from_dict(payload.task)
        if payload.mode == "real" and payload.connection is None:
            raise ValueError("请先配置模型服务")
        settings = payload.connection.settings() if payload.connection else Settings()
        try:
            run_id = manager.submit(
                task,
                settings,
                payload.mode,
                payload.scenario,
                payload.max_repairs,
                payload.workflow,
            )
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"run_id": run_id}

    @app.get("/api/runs")
    def history():
        return manager.history()

    @app.get("/api/runs/{run_id}")
    def detail(run_id: str):
        try:
            return manager.detail(run_id)
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(404, "找不到这次运行记录") from exc

    @app.post("/api/runs/{run_id}/cancel")
    def cancel(run_id: str):
        manager.cancel(run_id)
        return {"message": "已请求停止；当前步骤结束后生效，已完成结果会保留"}

    @app.get("/api/runs/{run_id}/download/{filename}")
    def download(run_id: str, filename: str):
        with manager.lock:
            return make_download(run_id, filename)

    def make_download(run_id: str, filename: str):
        try:
            directory = manager.directory(run_id)
            if filename == "result.zip":
                buffer = io.BytesIO()
                with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
                    for path in sorted(directory.iterdir()):
                        if path.is_file() and path.name in DOWNLOAD_FILES:
                            archive.write(path, path.name)
                    for path in sorted((directory / "versions").glob("v[0-9][0-9][0-9].py")):
                        archive.write(path, f"versions/{path.name}")
                return Response(
                    buffer.getvalue(),
                    media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="workflow-result.zip"'},
                )
            if filename not in DOWNLOAD_FILES:
                raise HTTPException(404, "文件不存在")
            content = (directory / filename).read_bytes()
        except OSError as exc:
            raise HTTPException(404, "文件暂不可用，请等待任务执行") from exc
        return Response(
            content,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    app.mount("/assets", StaticFiles(directory=root / "web" / "assets"), name="assets")
    return app
