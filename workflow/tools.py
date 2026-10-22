"""普通工具节点：运行固定的平均值验收用例，不调用模型。

此工具仅面向项目内的学习样例。子进程、临时目录和超时不构成安全沙箱。
接入其他任务时，需要由你提供与需求对应的验收用例。
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from .state import ValidationResult


def validate_code(code: str, code_version: int) -> ValidationResult:
    # 测试由流程程序固定持有；修复 Agent 只能修改 code。
    test_script = """
import runpy
import sys

scope = runpy.run_path(sys.argv[1])
average = scope['average']
cases = [([2, 4, 6], 4), ([], 0), ([-2, 2], 0), ([1, 2], 1.5), ([5], 5)]
for values, expected in cases:
    actual = average(values)
    assert actual == expected, f'average({values}) returned {actual}, expected {expected}'
print(f'{len(cases)} acceptance cases passed')
"""
    try:
        with tempfile.TemporaryDirectory(prefix="workflow-check-") as folder:
            candidate = Path(folder) / "candidate.py"
            candidate.write_text(code, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-I", "-c", test_script, str(candidate)],
                cwd=folder,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
        details = (result.stdout + result.stderr).strip()
        return ValidationResult(code_version, result.returncode == 0, details)
    except subprocess.TimeoutExpired:
        return ValidationResult(code_version, False, "验收执行超过 5 秒，已停止")
