# 配合代码阅读的学习练习

## 先跑一次

```powershell
python main.py
```

打开本次输出目录里的 `initial.py`、`final.py` 和 `report.json`，找到空列表处理前后的变化。

重要：DemoModel 是固定返回值。它能帮你学习流程，不能证明真实模型具备编码、审查或修复能力。

## 第一遍：只看流程

先看 `main.py` 中创建 `WorkflowState` 和调用 `run_workflow()` 的位置，再看 `runner.py`。

给自己回答这些问题：

1. 为什么 coder 在 while 外，fixer 在 while 内？
2. 为什么每轮要把原始 requirement 传给 Agent？
3. 为什么有了审查意见，还需要固定验收？
4. 为什么修复后要清空旧 issues 和 validation？
5. 修复次数是 0、1、2 时，分别执行了哪些步骤？

亲手把 `--max-repairs` 改为 0，先预测日志，再运行验证。

## 第二遍：跟踪数据

看 `state.py` 与 `agents.py`。在纸上写出 coder、reviewer、fixer 各自的参数和返回值。

打开 `report.json`，找到第 1 版失败和第 2 版通过的记录，检查 code_version。

亲手给状态增加一个字段，并在一次运行的报告中找到它。理解 `field(default_factory=list)` 为什么让每次任务拥有自己的列表。

## 第三遍：区分三种职责

- runner：负责流程控制，不让模型决定修复次数上限。
- agents：整理角色输入，检查输出格式，不决定下一步执行谁。
- tools：执行确定的检查工作，不需要模型。

看 `llm.py` 的 DemoModel，确认它实际上只是按角色返回固定数据。看 `prompts.py`，试着用自己的话重写一个角色的要求。

## 第四遍：做一个有反馈的修改

在 `tools.py` 的 cases 中增加一个平均值测试，例如 `([0, 0], 0)`，运行测试。

再观察 `stuck` 场景：为什么每次都修复了，最后仍然失败？怎样从日志判断？

```powershell
python main.py --scenario stuck
python -m unittest discover -s tests -v
```

## 第五遍：接回作业一

回到作业一的 `chat()`、`_run_loop()`、`_execute_tool()`，解释模型请求、工具调用请求和工具执行结果的区别。

在本项目的 `ModelClient.generate()` 中加入真实模型请求，先只替换 coder，再替换 reviewer 和 fixer。把 payload 转成消息，把模型输出解析回字典，保留格式校验。

如果需要 Agent 自主读取、保存或执行文件，再给相应角色接入作业一的工具循环。

真实模型接入后仍可先使用固定平均值需求和现有验收。更换任务时需要你另写对应测试，不能直接沿用平均值测试。

## 你应当能独立完成

- 不看说明，画出本项目的调用顺序。
- 新增一个角色，并明确它读取和更新什么数据。
- 修改结束条件，并解释为什么不会无限循环。
- 从报告中找出失败阶段、当前代码版本和未解决问题。

做到这些后，再把已有节点与状态迁移为 LangGraph 的 State、Node、Edge。
