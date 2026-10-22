# 多 Agent 代码审查 Workflow

软件工程 Homework 2：三个 Agent 协作完成 **编码、审查、修复**，通过共享状态与固定验收用例控制修复循环。

支持真实模型调用、自定义单文件 Python 函数任务、执行日志、逐步状态快照和结果报告。命令行作为交互入口，不依赖复杂调度框架。

## 功能与范围

- **编码 Agent**：根据需求与函数契约生成完整源码。
- **审查 Agent**：对照原始需求、当前代码与实际验证结果，给出严重程度、行号、证据和建议。
- **修复 Agent**：处理审查问题与验收失败，返回完整修复版本。
- **Workflow**：负责共享状态、顺序、分支、修复上限和结束判断。
- **验证工具**：检查语法和函数入口，执行用户固定的验收用例，支持异常、浮点容差和输入不可修改约束。

当前范围是单文件、同步 Python 函数，输入与预期输出采用 JSON 数据。它不是任意仓库的自动修改器。通过验收和审查代表满足本次检查条件，不等于证明全部输入正确。

## 环境与安装

需要 Python 3.11+。开发验证使用 Python 3.12；运行依赖只有 httpx 和 python-dotenv。

```powershell
cd E:\workflow
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

无需激活虚拟环境，直接使用其中的 Python 即可。

## 离线快速体验

```powershell
.\.venv\Scripts\python.exe main.py --mock
.\.venv\Scripts\python.exe main.py --mock --task examples/deduplicate.json
.\.venv\Scripts\python.exe main.py --mock --task examples/factorial.json
```

离线模式使用明确标记的固定模型结果，**不调用大模型**，但会真实执行验收。只支持未经修改的三个内置任务，用于复现流程与演示，不能据此宣称真实模型效果。

```powershell
# 初版直接通过
.\.venv\Scripts\python.exe main.py --mock --scenario pass

# 两次修复仍未解决，输出 needs_changes
.\.venv\Scripts\python.exe main.py --mock --scenario stuck

# 只生成和审查，不执行修复
.\.venv\Scripts\python.exe main.py --mock --max-repairs 0
```

## 真实模型运行

首次配置时复制 `.env.example` 为 `.env`，在 `.env` 中填写自己的密钥：

```dotenv
LLM_API_KEY=填写自己的密钥
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-flash
```

```powershell
.\.venv\Scripts\python.exe main.py --task examples/average.json
```

不加 `--mock` 时使用真实模型；缺少密钥会明确报错，不会自动伪装成离线成功。也可以设置 `DEEPSEEK_API_KEY`，但 `LLM_API_KEY` 优先。系统环境变量优先于 `.env`。

模型服务需要支持 `/chat/completions`、`response_format: json_object` 与标准消息格式。其他服务可修改地址和模型名，例如配置带 `/v1` 的基础地址。远程服务使用 HTTPS，本地模型服务允许 HTTP。

| 配置项 | 默认值 | 作用 |
|---|---|---|
| LLM_TIMEOUT | 60 | 单次请求超时，单位秒 |
| LLM_RETRIES | 2 | 网络、限流、服务临时失败的最大重试次数 |
| LLM_MAX_TOKENS | 4096 | 最大输出 Token；截断时明确失败 |
| OUTPUT_RETRIES | 1 | 输出 JSON 或字段不合规时的重新生成次数 |
| TEST_TIMEOUT | 5 | 每轮验收子进程超时，单位秒 |

真实模式会把需求、代码、验收结果与审查意见发送到所配置的模型服务。密钥只用于请求头，不写入提示词和报告。

## 自定义任务

复制一个 `examples/*.json`，改写原始需求、函数名和验收用例，然后使用真实模型运行：

```json
{
  "id": "add",
  "requirement": "实现 add(a, b)，返回两个数的和。",
  "function_name": "add",
  "cases": [
    {"name": "正数", "args": [2, 3], "expected": 5},
    {"name": "零与负数", "kwargs": {"a": 0, "b": -2}, "expected": -2}
  ]
}
```

用例字段：

- `name`：唯一名称；`args` 为位置参数数组，`kwargs` 为关键字参数对象，两者可以省略。
- `expected`：预期 JSON 值；也可以使用 `raises` 指定预期异常，两者必须二选一。
- `raises`：支持 ValueError、TypeError、ZeroDivisionError、IndexError、KeyError、OverflowError。
- `tolerance`：数字比较的绝对误差，默认为 0，也用于嵌套列表、对象中的数字。
- `check_input_unchanged`：是否要求调用后输入不变，默认为 false。

源码最多 64000 字符，任务文件最多 256 KB，任务需要 1 至 100 个验收用例。验收由用户固定，Agent 不持有修改测试的工具。

## 执行流程与输出

编码只运行一次。每轮先验证当前版本，再审查；验收通过且问题列表为空才成功，否则在次数上限内修复并重新验证。所有严重程度的问题都需要处理，纯风格偏好不应被报告为缺陷。

默认最多修复两次，也就是最多出现三个代码版本。CLI 退出码：0 为 completed；1 为 needs_changes；2 为 failed 或配置错误；130 为用户中断。

每次运行在 `runs/<运行编号>/` 中保存：

| 文件 | 内容 |
|---|---|
| task.json | 本次固定任务与验收用例 |
| initial.py / final.py | 初版与最后候选代码；失败时 final.py 也不代表正确 |
| versions/ | 各次代码版本 |
| snapshots/ | 每个步骤的完整状态快照，包含当时的审查和验证 |
| events.jsonl / run.log | 节点事件、重试信息和执行日志 |
| report.json / report.md | 最终状态、用例结果、问题、错误和模型用量 |

发生错误后已保存的步骤可用于诊断；当前不支持从快照自动续跑。模型未提供用量时 Token 数为 0，不能据此理解为没有计费。

验收在带超时的子进程与临时目录中执行，**不是安全沙箱**。仅运行自己的课程样例；执行不可信外部代码需要容器等独立隔离。

## 测试与代码检查

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
```

自动化测试默认不使用真实密钥：覆盖三个任务的直接通过、修复成功、达到上限、超时、模型请求重试、格式恢复、版本一致性与打包后运行。HTTP MockTransport 测试会经过真实请求适配代码，但不等于真实模型服务已联调。

## 文件结构与阅读顺序

```text
main.py                  命令行入口
workflow/
  task.py                任务与验收契约
  state.py               共享状态与结构化结果
  runner.py              顺序、分支和修复循环
  agents.py              三个 Agent 与输出校验
  prompts.py             角色提示词
  llm.py                 真实 API 调用与重试
  tools.py               验证工具
  _test_worker.py         验收子进程
  artifacts.py            日志、快照与报告
  config.py               配置加载
  mock.py                 离线模型
examples/                 三个完整任务
tests/                    自动化测试
docs/                     作业对应说明、演示步骤
scripts/package_submission.py  提交打包
```

建议先读 main、state、runner，再看 agents、prompts、llm，最后看验证与报告。架构和扩展位置见 [Design.md](Design.md)。

## 作业提交

本项目对应 Homework 2 的代码审查方向，要求映射见 [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md)。一分钟演示步骤见 [docs/DEMO.md](docs/DEMO.md)。

```powershell
.\.venv\Scripts\python.exe scripts/package_submission.py --name "自己的学号姓名"
```

压缩包位于 `dist/`，包含源码、配置示例、任务、测试和文档，排除 `.env`、`.git`、虚拟环境和运行输出。同名文件已存在时拒绝覆盖。

按课件将小于 200 MB 的“学号姓名”压缩包提交至“002Homework2”；截止时间为北京时间 2026 年 10 月 25 日 24:00。仓库当前为私有，如通过链接供老师检查，需要你按课程要求提供访问方式。演示视频不超过一分钟，为可选项。

## 接口依据

真实请求按 [DeepSeek JSON 输出说明](https://api-docs.deepseek.com/guides/json_mode/) 和 [错误码说明](https://api-docs.deepseek.com/quick_start/error_codes/) 实现。服务和模型可用性取决于你的账号与配置。
