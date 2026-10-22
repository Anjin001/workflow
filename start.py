"""启动本地网页，自动选择端口并打开浏览器；重复启动会复用已有窗口。"""

import argparse
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from workflow.web import create_app

ROOT = Path(__file__).resolve().parent
INSTANCE_FILE = ROOT / "runs" / ".web-instance.json"


def existing_instance() -> str | None:
    try:
        info = json.loads(INSTANCE_FILE.read_text(encoding="utf-8"))
        port = info["port"]
        if type(port) is not int or not 1024 <= port <= 65535:
            return None
        url = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
            health = json.load(response)
        if health.get("app") == "code-review-workflow" and health.get("pid") == info["pid"]:
            return url
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return None


def bind_socket(port: int) -> socket.socket:
    for candidate in range(port, min(port + 20, 65536)):
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            connection.bind(("127.0.0.1", candidate))
            return connection
        except OSError:
            connection.close()
    raise OSError("未找到可用本地端口，请关闭旧窗口或稍后重试")


def open_when_ready(url: str) -> None:
    for _ in range(50):
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=0.5):
                webbrowser.open(url)
                return
        except (OSError, urllib.error.URLError):
            time.sleep(0.1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动 Workflow 网页工作台")
    parser.add_argument("--no-browser", action="store_true", help="启动服务但不自动打开浏览器")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65516:
        parser.error("端口必须在 1024 至 65516 之间")
    existing = existing_instance()
    if existing:
        print(f"工作台已启动：{existing}")
        if not args.no_browser:
            webbrowser.open(existing)
        return 0
    try:
        connection = bind_socket(args.port)
    except OSError as exc:
        print(f"启动失败：{exc}")
        return 2
    port = connection.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(), host="127.0.0.1", port=port, access_log=False, log_level="warning"
        )
    )
    INSTANCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    INSTANCE_FILE.write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    print(
        f"\nWorkflow 工作台：{url}\n"
        "浏览器未自动打开时，可复制此地址。关闭此窗口或按 Ctrl+C 停止服务。\n"
    )
    try:
        server.run(sockets=[connection])
    finally:
        connection.close()
        try:
            if json.loads(INSTANCE_FILE.read_text(encoding="utf-8")).get("pid") == os.getpid():
                INSTANCE_FILE.unlink()
        except (OSError, ValueError):
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
