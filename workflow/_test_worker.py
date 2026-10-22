"""验收子进程入口。仅使用标准库，通过标准输入接收固定任务与代码路径。"""

import builtins
import contextlib
import copy
import json
import math
import runpy
import sys


def equivalent(actual, expected, tolerance):
    if type(expected) is bool or expected is None:
        return type(actual) is type(expected) and actual == expected
    if type(expected) in (int, float):
        if type(actual) not in (int, float):
            return False
        if tolerance == 0:
            return actual == expected
        return math.isclose(actual, expected, rel_tol=0, abs_tol=tolerance)
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(
                equivalent(left, right, tolerance)
                for left, right in zip(actual, expected, strict=True)
            )
        )
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and actual.keys() == expected.keys()
            and all(equivalent(actual[key], value, tolerance) for key, value in expected.items())
        )
    return type(actual) is type(expected) and actual == expected


def evaluate(function, case):
    original_args = copy.deepcopy(case["args"])
    original_kwargs = copy.deepcopy(case["kwargs"])
    try:
        actual = function(*case["args"], **case["kwargs"])
    except Exception as exc:
        expected_type = getattr(builtins, case.get("raises", ""), None)
        passed = expected_type is not None and isinstance(exc, expected_type)
        detail = f"{type(exc).__name__}: {str(exc)[:1000]}"
    else:
        if "raises" in case:
            passed = False
            detail = f"应抛出 {case['raises']}，实际返回 {repr(actual)[:1000]}"
        else:
            passed = equivalent(actual, case["expected"], case["tolerance"])
            detail = f"实际：{repr(actual)[:1000]}；预期：{repr(case['expected'])[:1000]}"
    if case["check_input_unchanged"] and (
        not equivalent(case["args"], original_args, 0)
        or not equivalent(case["kwargs"], original_kwargs, 0)
    ):
        passed = False
        detail += "；函数修改了不允许修改的输入参数"
    return {"name": case["name"], "passed": passed, "detail": detail}


def main():
    payload = json.load(sys.stdin)
    # 被测函数的打印进入 stderr，stdout 专门传递验收结果。
    with contextlib.redirect_stdout(sys.stderr):
        scope = runpy.run_path(payload["code_path"])
        function = scope[payload["function_name"]]
        results = [evaluate(function, case) for case in payload["cases"]]
    print(json.dumps({"cases": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
