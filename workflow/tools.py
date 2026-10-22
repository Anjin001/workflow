"""检查语法与函数入口，并在独立子进程执行固定验收。"""

import ast
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from .state import ValidationResult
from .task import TaskSpec


def code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


class CodeValidator:
    """临时目录和超时用于控制普通错误；它们不构成安全沙箱。"""

    def __init__(self, timeout: int = 5) -> None:
        self.timeout = timeout

    def validate(self, task: TaskSpec, code: str, version: int) -> ValidationResult:
        digest = code_hash(code)

        def failed(details: str) -> ValidationResult:
            return ValidationResult(version, digest, False, details)

        try:
            tree = ast.parse(code)
        except (SyntaxError, ValueError) as exc:
            return failed(f"语法检查失败：{exc}")
        if not any(
            isinstance(node, ast.FunctionDef) and node.name == task.function_name
            for node in tree.body
        ):
            return failed(f"源码未在顶层定义同步函数 {task.function_name}")

        worker = Path(__file__).with_name("_test_worker.py")
        try:
            with tempfile.TemporaryDirectory(prefix="code-review-") as directory:
                candidate = Path(directory) / "candidate.py"
                candidate.write_text(code, encoding="utf-8")
                payload = {
                    "code_path": str(candidate),
                    "function_name": task.function_name,
                    "cases": [case.to_dict() for case in task.cases],
                }
                # 输出写入临时文件，避免打印过多时占用主进程内存。
                with (
                    (Path(directory) / "stdout.log").open("w+b") as stdout,
                    (Path(directory) / "stderr.log").open("w+b") as stderr,
                ):
                    process = subprocess.run(
                        [sys.executable, "-I", "-X", "utf8", str(worker)],
                        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                        stdout=stdout,
                        stderr=stderr,
                        cwd=directory,
                        timeout=self.timeout,
                    )
                    stdout.seek(0)
                    output = stdout.read(256_000).decode("utf-8", errors="replace")
                    stderr.seek(0)
                    errors = stderr.read(6000).decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            return failed(f"验收执行超过 {self.timeout} 秒，子进程已停止")
        if process.returncode:
            return failed(f"验收子进程退出码 {process.returncode}：{errors}")
        try:
            data = json.loads(output)
            cases = data["cases"]
            if not isinstance(cases, list) or len(cases) != len(task.cases):
                raise ValueError("用例数量不匹配")
            for actual, expected in zip(cases, task.cases, strict=True):
                if (
                    not isinstance(actual, dict)
                    or actual.get("name") != expected.name
                    or type(actual.get("passed")) is not bool
                    or not isinstance(actual.get("detail"), str)
                ):
                    raise ValueError("验收结果字段不合法")
        except (ValueError, KeyError, TypeError) as exc:
            return failed(f"无法读取完整验收结果：{exc}")
        passed_count = sum(case["passed"] for case in cases)
        return ValidationResult(
            version,
            digest,
            passed_count == len(cases),
            f"{passed_count}/{len(cases)} 个验收用例通过",
            cases,
        )
