# 代码审查 Workflow · Homework 2

一个方便逐步阅读和修改的多 Agent 流程模板：需求、编码、验证、审查、修复、重新验证。

## 当前完成范围

已经实现顺序执行、共享状态、有限修复循环、结果保存和错误记录。默认运行固定的平均值样例，三个角色的输出来自 `DemoModel`，没有调用真实模型，也没有实现真实 Agent 的工具循环。

验收工具会实际运行 Python 测试。`--mode real` 目前会明确报告“真实模型尚未接入”，需要你实现模型接口。模板尚不能处理任意编程需求，也不是已完成的作业交付。

## 运行

需要 Python 3.10 或更新版本，仅使用标准库，无需安装依赖和配置密钥。

```powershell
cd E:\workflow
python main.py
```

默认场景会生成一个遗漏空列表处理的 `average` 函数，检查失败后修复，再检查通过。

```text
[coder] 已生成第 1 版代码
[validate] 验收未通过
[reviewer] 审查发现 1 个问题
[fixer] 第 1 次修复，生成第 2 版代码
[validate] 验收通过
[reviewer] 审查发现 0 个问题
[end] 当前代码通过验收，且审查未提出待处理问题
```

其他路径：

```powershell
python main.py --scenario pass
python main.py --scenario stuck
python main.py --max-repairs 0
python -m unittest discover -s tests -v
```

`stuck` 和 `--max-repairs 0` 在存在问题时返回退出码 1，这是预期结果。执行异常返回 2，通过返回 0。

每次运行会创建 `runs/<本次运行编号>/`，保存 `initial.py`、`final.py` 和 `report.json`。整个 `runs/` 已由 Git 忽略。生成代码之前就失败时，只保存报告。

## 先读哪些文件

| 顺序 | 文件 | 要理解的问题 |
|---|---|---|
| 1 | `main.py` | 参数怎样进入程序，怎样启动流程？ |
| 2 | `workflow/state.py` | 各步骤共用哪些任务数据？ |
| 3 | `workflow/runner.py` | 谁决定执行顺序，什么时候修复和终止？ |
| 4 | `workflow/agents.py` | 每个角色具体收到什么，返回什么？ |
| 5 | `workflow/llm.py` | 演示结果从哪里来，真实模型接在哪里？ |
| 6 | `workflow/tools.py` | 验证依据是什么，如何对应当前代码？ |
| 7 | `workflow/prompts.py` | 三个角色的要求有什么不同？ |

配合 `LEARNING.md` 做小修改，`Design.md` 描述架构和数据流。

## 下一阶段

在 `ModelClient.generate()` 接入作业一的模型请求，逐个替换固定演示。需要支持工具时，复用作业一的工具调用循环。更换任务时，同时提供相应的验收用例，再考虑 LangGraph。

当前验证使用子进程、临时目录和超时，不构成安全沙箱，仅用于自己的学习样例。

不要提交 API Key、`.env`、虚拟环境和运行输出。
