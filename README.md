# 多 Agent 代码审查 Workflow

通过多个 Agent 协作完成 **编码、审查、修复**，通过共享状态与固定验收用例控制修复循环。

支持网页设置模型、自定义需求、图形化验收编辑、真实模型调用、执行日志、版本对比与结果下载。保留命令行入口，底层不依赖复杂调度框架。

## 推荐用法：双击打开网页

需要 Python 3.11+，无需安装 Node.js。**双击项目根目录的 `start.bat`**，首次会自动准备依赖，随后打开浏览器。

1. 右上角进入“模型设置”，填写 API Key、模型服务地址和模型名称。
2. 输入自己的编程需求，点击“准备任务”。
3. 在网页确认模型建议的函数名和验收用例，再点击“开始审查”。
4. 查看实时阶段、审查意见、验收结果及代码版本，复制代码或下载完整结果。

也可以直接点击“无需 Key，体验完整流程”。它会使用明确标注的离线示例，真实执行验收并展示一次修复。

**网页使用不需要编辑 .env，不需要创建 JSON 文件，也不需要输入命令。** 服务地址和模型名可以记住；API Key 不写入浏览器存储或项目文件，刷新页面后需重新填写。

支持 DeepSeek、其他 Chat Completions 兼容接口，以及本地模型的兼容接口。可以读取模型列表，也能手动输入模型名称。基础地址和完整的 `/chat/completions` 地址都可以粘贴。

默认网页地址是 `http://127.0.0.1:8765`；被占用时会自动选择其他端口。重复双击会打开已有工作台。关闭启动窗口停止服务，关掉网页不会停止后台任务。

详细交互说明见 [docs/INTERFACE.md](docs/INTERFACE.md)。以下命令主要供开发、测试和原命令行方式使用。

## 可视化工作流与验证者

角色面板将名称、说明与 Prompt 分开显示。自定义角色可编辑完整 Prompt；默认模型角色显示实际内置系统 Prompt，并支持可选补充。程序控制与验收工具节点不调用模型。画布默认固定 100%，只有手动调整比例或点击「适应画布」才会改变缩放。

进入左侧「工作流设计」，添加自定义角色、配置提示词和读取信息，拖动节点并手动连线。结构检查通过后点击「保存并使用」，后续任务会按这张图执行。支持流程库、导入导出、撤销、缩放及运行图中的逐节点输出查看。

默认模板仍是三个 Agent。可点击「＋ 问题验证者」或选择四角色模板，独立核对审查候选，输出已确认、已驳回、待确认。程序检查源码引用与代码版本，待确认问题不会自动通过，验收失败不会被模型驳回覆盖。

第一版允许在受约束的主路径、修复路径或通过路径插入自定义分析角色，保留编码 → 验收 → 审查 → 可选验证 → 判定的核心顺序。暂不支持任意循环、并行或让自定义角色执行命令。流程详情、实现入口与效果边界见 [docs/WORKFLOWS.md](docs/WORKFLOWS.md)。

## 功能与范围

- **编码 Agent**：根据需求与函数契约生成完整源码。
- **审查 Agent**：对照原始需求、当前代码与实际验证结果，给出严重程度、行号、证据和建议。
- **修复 Agent**：处理审查问题与验收失败，返回完整修复版本。
- **Workflow**：负责共享状态、顺序、分支、修复上限和结束判断。
- **验证工具**：检查语法和函数入口，执行用户固定的验收用例，支持异常、浮点容差和输入不可修改约束。

当前范围是单文件、同步 Python 函数，输入与预期输出采用 JSON 数据。它不是任意仓库的自动修改器。通过验收和审查代表满足本次检查条件，不等于证明全部输入正确。

## 环境与安装

需要 Python 3.11+。开发验证使用 Python 3.12；运行依赖为 httpx、python-dotenv、FastAPI 和 Uvicorn。

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

## 真实模型运行（命令行方式）

网页中直接填写设置即可。只有选择命令行入口时才需要以下 .env 配置。

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
| LLM_JSON_MODE | true | 是否发送服务原生 JSON 输出参数；不支持时可关闭 |

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

源码最多 64000 字符，任务文件最多 256 KB，任务需要 1 至 100 个验收用例。验收由用户固定，Agent 不持有修改测试的工具。网页可先由编码角色生成验收草稿，必须经用户确认后才启动；草稿生成不计入工作流报告的执行用量。

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

发生错误后已保存的步骤可用于诊断；当前不支持从快照自动续跑。模型未提供用量时 Token 数为 0，不能据此理解为没有计费。网页支持步骤边界停止，状态为 cancelled；服务关闭前未结束的记录重开后显示为中断。

验收在带超时的子进程与临时目录中执行，**不是安全沙箱**。仅运行可信的代码；执行不可信外部代码需要容器等独立隔离。

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
start.bat / start.py      双击启动网页，自动打开浏览器
main.py                  保留的命令行入口
web/                     HTML、CSS、JavaScript，无需前端构建
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
  web.py / web_models.py  本地页面、请求校验和连接测试
  web_service.py          后台运行、历史与协作式停止
examples/                 三个完整任务
tests/                    自动化测试
docs/                     功能说明、使用指南与演示步骤
scripts/package_source.py  源码打包
```

建议先读 state、runner，再看 agents、prompts、llm；网页交互从 web.py 和 web/assets/app.js 开始。架构和扩展位置见 [Design.md](Design.md)。

## 源码打包

```powershell
.\.venv\Scripts\python.exe scripts/package_source.py --name "workflow-source"
```

压缩包位于 `dist/`，包含启动文件、网页、源码、配置示例、任务、测试和文档，排除 `.env`、`.git`、虚拟环境、本机流程库和运行输出。同名文件已存在时拒绝覆盖。

功能范围见 [docs/FEATURES.md](docs/FEATURES.md)，快速演示见 [docs/DEMO.md](docs/DEMO.md)。

前端缩放和连线几何的回归测试可以使用 Node.js 运行；日常启动网页不需要 Node.js：

```powershell
node --test tests/graph_view.test.cjs
```

## 接口依据

真实请求按 [DeepSeek JSON 输出说明](https://api-docs.deepseek.com/guides/json_mode/) 和 [错误码说明](https://api-docs.deepseek.com/quick_start/error_codes/) 实现。服务和模型可用性取决于你的账号与配置。
