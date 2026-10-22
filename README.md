# 代码审查 Workflow · Homework 2

一个用于学习多 Agent 协作的 Python 项目。计划实现：需求输入、编码、审查、修复、再次验证。

## 当前状态

这是项目初始化和学习骨架。模型调用、Agent 行为和工作流尚未实现，不能当成已完成的作业提交。

为方便理解，先用普通 Python 实现流程，再按需要迁移到 LangGraph。

## 快速开始

需要 Python 3.10 或更新版本。目前仅使用标准库，无需 API Key。

```powershell
cd E:\workflow
python main.py --requirement "实现 average(numbers)，空列表返回 0"
```

这条命令只展示初始化后的任务状态，不会调用模型或生成代码。

## 阅读顺序

1. `main.py`：需求怎样进入程序。
2. `workflow/state.py`：任务数据怎样保存。
3. `workflow/agents.py`：各 Agent 需要什么输入、返回什么结果。
4. `workflow/runner.py`：由你实现 Agent 调用顺序和修复循环。
5. `LEARNING.md`：分阶段练习与完成标准。

## 计划架构

- 编码 Agent：接收需求，生成代码。
- 审查 Agent：接收原始需求与当前代码，返回问题列表。
- 修复 Agent：接收需求、代码与问题，返回修改后的代码。
- Workflow：保存共享状态，控制执行顺序、验证与终止。
- 验证工具：后续加入固定验收测试，检查当前代码版本。

最终计划复用作业一的模型调用和工具循环，使用 Python、LangChain、DeepSeek API 与 pytest。先逐个完成练习，再添加依赖。

不要提交 API Key、`.env`、虚拟环境或模型运行输出。
