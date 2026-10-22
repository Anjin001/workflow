"use strict";

const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="workflow-token"]').content;
const defaults = {
  mode: "real",
  provider: "deepseek",
  baseUrl: "https://api.deepseek.com",
  model: "deepseek-flash",
  timeout: 60,
  jsonMode: true,
  scenario: "repair",
};
let saved = {};
try {
  saved = JSON.parse(localStorage.getItem("workflow.settings.v1") || "{}");
} catch {
  /* 浏览器禁用本地存储时，仍然可以使用当前页面。 */
}
const app = {
  config: { ...defaults, ...saved },
  apiKey: "",
  settingsMode: "real",
  examples: [],
  task: null,
  confirmed: false,
  maxRepairs: 2,
  currentRun: null,
  selectedVersion: "latest",
  tab: "code",
  compare: false,
  generation: 0,
  poll: null,
  panelSignature: "",
  preparing: false,
  submitting: false,
};
const labels = {
  pending: "等待开始",
  running: "运行中",
  completed: "已完成",
  needs_changes: "仍需修改",
  failed: "执行失败",
  cancelled: "已停止",
  interrupted: "运行已中断",
};
const stages = {
  start: "开始",
  coder: "编码",
  validate: "验收",
  reviewer: "审查",
  fixer: "修复",
  end: "结束",
  error: "错误",
};
const exceptions = [
  "ValueError",
  "TypeError",
  "ZeroDivisionError",
  "IndexError",
  "KeyError",
  "OverflowError",
];
const escapeHtml = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[char],
  );
const isRunning = (report) => ["pending", "running"].includes(report?.status);
const dialog = (id) => {
  if (!$(id).open) $(id).showModal();
};

async function api(path, payload, raw = false) {
  let response;
  try {
    response = await fetch(path, {
      method: payload === undefined ? "GET" : "POST",
      headers: {
        "X-Workflow-Token": token,
        ...(payload === undefined
          ? {}
          : { "Content-Type": "application/json" }),
      },
      body: payload === undefined ? undefined : JSON.stringify(payload),
      cache: "no-store",
    });
  } catch {
    throw new Error("本地服务未连接，请重新双击 start.bat 启动工作台。");
  }
  if (!response.ok) {
    let message = "请求未完成，请稍后重试。";
    try {
      const data = await response.json();
      if (typeof data.detail === "string") message = data.detail;
    } catch {
      /* 服务未返回 JSON 时，使用通用说明。 */
    }
    throw new Error(message);
  }
  return raw ? response : response.json();
}

let toastTimer;
function toast(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    $("toast").hidden = true;
  }, 5500);
}

function connection() {
  return {
    api_key: app.apiKey,
    base_url: app.config.baseUrl,
    model: app.config.model,
    timeout: app.config.timeout,
    json_mode: app.config.jsonMode,
  };
}

function configured() {
  let local = false;
  try {
    local = ["localhost", "127.0.0.1", "[::1]"].includes(
      new URL(app.config.baseUrl).hostname,
    );
  } catch {
    return false;
  }
  return (
    app.config.mode === "mock" ||
    Boolean(app.config.model && (app.apiKey || local))
  );
}

function renderConfig() {
  const mock = app.config.mode === "mock";
  $("mode-label").textContent = mock ? "离线示例" : "真实模型";
  $("model-label").textContent = mock
    ? "离线体验"
    : configured()
      ? app.config.model
      : "配置模型";
  $("model-dot").className = `dot${configured() ? " green" : ""}`;
  updateComposer();
}

function showSettings() {
  app.settingsMode = app.config.mode;
  $("provider").value = app.config.provider;
  $("base-url").value = app.config.baseUrl;
  $("api-key").value = app.apiKey;
  $("api-key").type = "password";
  $("toggle-key").textContent = "显示";
  $("model-name").value = app.config.model;
  $("request-timeout").value = app.config.timeout;
  $("json-mode").checked = app.config.jsonMode;
  $("mock-scenario").value = app.config.scenario;
  $("connection-feedback").textContent = "";
  renderSettingsMode();
  dialog("settings-dialog");
}

function renderSettingsMode() {
  document.querySelectorAll("[data-mode]").forEach((button) => {
    button.classList.toggle(
      "selected",
      button.dataset.mode === app.settingsMode,
    );
  });
  $("real-settings").hidden = app.settingsMode !== "real";
  $("mock-settings").hidden = app.settingsMode !== "mock";
  $("real-settings")
    .querySelectorAll("input,select,button")
    .forEach((control) => {
      control.disabled = app.settingsMode !== "real";
    });
  $("key-optional").hidden = $("provider").value !== "local";
}

function settingsFields() {
  return {
    api_key: $("api-key").value.trim(),
    base_url: $("base-url").value.trim(),
    model: $("model-name").value.trim(),
    timeout: Number($("request-timeout").value),
    json_mode: $("json-mode").checked,
  };
}

async function saveSettings(event) {
  event.preventDefault();
  const button = $("settings-form").querySelector('[type="submit"]');
  button.disabled = true;
  try {
    const values = settingsFields();
    if (app.settingsMode === "real") {
      const normalized = await api("/api/connection/validate", values);
      values.base_url = normalized.base_url;
      values.model = normalized.model;
    }
    app.apiKey = values.api_key;
    app.config = {
      mode: app.settingsMode,
      provider: $("provider").value,
      baseUrl: values.base_url,
      model: values.model,
      timeout: values.timeout,
      jsonMode: values.json_mode,
      scenario: $("mock-scenario").value,
    };
    // 只记住非敏感配置，绝不保存 API Key。
    try {
      localStorage.setItem("workflow.settings.v1", JSON.stringify(app.config));
    } catch {
      /* 可选记忆 */
    }
    $("settings-dialog").close();
    renderConfig();
    toast(
      app.config.mode === "mock"
        ? "已切换到离线体验"
        : "模型设置已应用到当前页面",
    );
  } catch (error) {
    $("connection-feedback").className = "inline-feedback";
    $("connection-feedback").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function testConnection() {
  const button = $("check-connection");
  button.disabled = true;
  button.textContent = "正在连接…";
  $("connection-feedback").className = "inline-feedback";
  $("connection-feedback").textContent = "";
  try {
    const data = await api("/api/connection/check", settingsFields());
    $("base-url").value = data.base_url;
    $("model-options").innerHTML = data.models
      .map((model) => `<option value="${escapeHtml(model)}"></option>`)
      .join("");
    if (data.models.length && !data.models.includes($("model-name").value))
      $("model-name").value = data.models[0];
    $("connection-feedback").textContent = data.message;
    $("connection-feedback").className = "inline-feedback success";
  } catch (error) {
    $("connection-feedback").textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "测试连接并读取模型";
  }
}

function updateComposer() {
  const ready =
    app.task &&
    app.task.requirement === $("requirement").value.trim() &&
    app.confirmed;
  $("case-count").textContent = app.task?.cases.length || 0;
  $("submit-task").disabled = app.preparing || app.submitting;
  $("submit-task").firstElementChild.textContent = app.preparing
    ? "准备中…"
    : app.submitting
      ? "启动中…"
      : ready
        ? "开始审查"
        : "准备任务";
  $("draft-status").hidden = !app.task;
  $("draft-status").textContent = app.task
    ? `${app.task.function_name} · ${app.task.cases.length} 个验收用例 · ${app.confirmed ? "已确认，可以开始审查" : "请先核对并确认验收"}`
    : "";
  $("composer-hint-text").textContent =
    app.config.mode === "mock"
      ? "离线模式只支持内置示例；自定义需求请连接真实模型。"
      : "先整理接口与验收用例，确认后开始编码和审查。";
}

function loadExample(task) {
  newTask(false);
  app.task = structuredClone(task);
  app.confirmed = true;
  $("requirement").value = task.requirement;
  updateComposer();
  $("requirement").focus();
}

async function quickDemo() {
  if (!app.examples.length) {
    toast("示例正在加载，请稍后再试");
    return;
  }
  $("settings-dialog").close();
  app.config.mode = "mock";
  app.config.scenario = "repair";
  renderConfig();
  loadExample(
    app.examples.find((task) => task.id === "average") || app.examples[0],
  );
  await startRun();
}

function newTask(focus = true) {
  app.generation += 1;
  clearTimeout(app.poll);
  app.currentRun = null;
  app.task = null;
  app.confirmed = false;
  app.maxRepairs = 2;
  app.panelSignature = "";
  $("requirement").value = "";
  $("result").hidden = true;
  $("welcome").hidden = false;
  document.body.classList.remove("sidebar-open");
  updateComposer();
  refreshHistory();
  if (focus) $("requirement").focus();
}

async function submitTask(event) {
  event.preventDefault();
  if (app.preparing || app.submitting) return;
  const requirement = $("requirement").value.trim();
  if (!requirement) {
    toast("先描述你想实现的功能");
    $("requirement").focus();
    return;
  }
  if (!configured()) {
    showSettings();
    return;
  }
  if (app.task && app.task.requirement === requirement) {
    if (app.confirmed) await startRun();
    else showCases();
    return;
  }
  if (app.config.mode === "mock") {
    toast("离线模式请选择下方示例；自定义需求请切换到真实模型");
    return;
  }
  app.preparing = true;
  const generation = app.generation;
  $("requirement").readOnly = true;
  updateComposer();
  try {
    const data = await api("/api/tasks/prepare", {
      requirement,
      connection: connection(),
    });
    if (generation !== app.generation) return;
    app.task = data.task;
    app.confirmed = false;
    showCases();
    toast("接口和验收草稿已准备好，请核对预期结果后确认");
  } catch (error) {
    toast(error.message);
  } finally {
    app.preparing = false;
    $("requirement").readOnly = false;
    updateComposer();
  }
}

function showCases() {
  if (!$("requirement").value.trim()) {
    toast("先在输入框描述你的需求");
    $("requirement").focus();
    return;
  }
  const task = app.task || { id: "custom-task", function_name: "", cases: [] };
  $("task-id").value = task.id;
  $("function-name").value = task.function_name;
  $("max-repairs").value = app.maxRepairs;
  $("cases-feedback").textContent = "";
  $("cases-intro").textContent = app.confirmed
    ? "这是当前固定验收。改动后，下一次运行使用新用例。"
    : "模型建议仅供确认：请特别核对预期结果和未明确的默认约定。";
  $("case-editor").innerHTML = task.cases.map(caseRow).join("");
  if (!task.cases.length) addCase();
  dialog("cases-dialog");
}

function caseRow(test, index) {
  const type = test.raises ? "raises" : "expected";
  const value = test.raises || JSON.stringify(test.expected ?? null);
  return `<details class="case-row" ${index === 0 ? "open" : ""}><summary><span>${escapeHtml(test.name || `用例 ${index + 1}`)}</span><span class="case-preview">${escapeHtml(JSON.stringify(test.args || []))} → ${escapeHtml(value)}</span></summary><div class="case-fields">
    <label class="case-full">用例名称<input data-field="name" value="${escapeHtml(test.name || `用例 ${index + 1}`)}" maxlength="120"></label>
    <label>位置参数（JSON 数组）<input data-field="args" value="${escapeHtml(JSON.stringify(test.args || []))}" spellcheck="false"></label>
    <label>关键字参数（JSON 对象）<input data-field="kwargs" value="${escapeHtml(JSON.stringify(test.kwargs || {}))}" spellcheck="false"></label>
    <label>验收方式<select data-field="type"><option value="expected" ${type === "expected" ? "selected" : ""}>检查返回值</option><option value="raises" ${type === "raises" ? "selected" : ""}>检查抛出异常</option></select></label>
    <label data-expected ${type === "raises" ? "hidden" : ""}>预期结果（JSON 值）<input data-field="expected" value="${escapeHtml(JSON.stringify(test.expected ?? null))}" spellcheck="false"></label>
    <label data-raises ${type !== "raises" ? "hidden" : ""}>预期异常<select data-field="raises">${exceptions.map((name) => `<option ${test.raises === name ? "selected" : ""}>${name}</option>`).join("")}</select></label>
    <label>浮点绝对误差<input data-field="tolerance" type="number" min="0" step="any" value="${Number(test.tolerance || 0)}"></label>
    <label class="checkbox-row"><input data-field="unchanged" type="checkbox" ${test.check_input_unchanged ? "checked" : ""}> 不允许修改输入参数</label>
    <button class="case-delete" type="button">删除此用例</button></div></details>`;
}

function addCase() {
  const count = $("case-editor").children.length;
  if (count >= 100) {
    toast("最多添加 100 个验收用例");
    return;
  }
  $("case-editor").insertAdjacentHTML(
    "beforeend",
    caseRow({ name: `用例 ${count + 1}`, args: [], expected: null }, count),
  );
  $("case-editor").lastElementChild.open = true;
}

function collectCases() {
  return [...$("case-editor").querySelectorAll(".case-row")].map(
    (row, index) => {
      const field = (name) => row.querySelector(`[data-field="${name}"]`);
      let args, kwargs, expected;
      try {
        args = JSON.parse(field("args").value);
        kwargs = JSON.parse(field("kwargs").value);
      } catch {
        throw new Error(
          `用例 ${index + 1}：参数不是有效 JSON，请检查括号和引号`,
        );
      }
      const test = {
        name: field("name").value.trim(),
        args,
        kwargs,
        tolerance: Number(field("tolerance").value),
        check_input_unchanged: field("unchanged").checked,
      };
      if (field("type").value === "raises") test.raises = field("raises").value;
      else {
        try {
          expected = JSON.parse(field("expected").value);
        } catch {
          throw new Error(
            `用例 ${index + 1}：预期结果不是有效 JSON，文本请用双引号包裹`,
          );
        }
        test.expected = expected;
      }
      return test;
    },
  );
}

async function saveCases() {
  $("save-cases").disabled = true;
  try {
    const maxRepairs = Number($("max-repairs").value);
    if (!Number.isInteger(maxRepairs) || maxRepairs < 0 || maxRepairs > 10)
      throw new Error("修复次数必须为 0 至 10 的整数");
    const draft = {
      id: $("task-id").value.trim(),
      function_name: $("function-name").value.trim(),
      requirement: $("requirement").value.trim(),
      cases: collectCases(),
    };
    const task = await api("/api/tasks/validate", draft);
    app.task = task;
    app.confirmed = true;
    app.maxRepairs = maxRepairs;
    $("cases-dialog").close();
    updateComposer();
    toast("验收已确认，点击“开始审查”即可运行");
  } catch (error) {
    $("cases-feedback").textContent = error.message;
  } finally {
    $("save-cases").disabled = false;
  }
}

async function importTask(event) {
  const file = event.target.files[0];
  if (!file) return;
  try {
    if (file.size > 256000) throw new Error("任务文件不能超过 256 KB");
    const task = await api(
      "/api/tasks/validate",
      JSON.parse(await file.text()),
    );
    app.task = task;
    app.confirmed = false;
    $("requirement").value = task.requirement;
    showCases();
    updateComposer();
  } catch (error) {
    $("cases-feedback").textContent = error.message;
  } finally {
    event.target.value = "";
  }
}

async function startRun() {
  if (!app.task || app.submitting) return;
  if (!configured()) {
    showSettings();
    return;
  }
  app.submitting = true;
  updateComposer();
  try {
    const payload = {
      task: app.task,
      mode: app.config.mode,
      scenario: app.config.scenario,
      max_repairs: app.maxRepairs,
    };
    if (app.config.mode === "real") payload.connection = connection();
    const data = await api("/api/runs", payload);
    await loadRun(data.run_id);
    await refreshHistory();
  } catch (error) {
    toast(error.message);
  } finally {
    app.submitting = false;
    updateComposer();
  }
}

async function refreshHistory() {
  try {
    const data = await api("/api/runs");
    renderHistory(data);
  } catch {
    /* 主页面会在操作或轮询失败时给出连接提示，避免重复弹出。 */
  }
}

function renderHistory(data) {
  $("history-count").textContent = data.items.length;
  $("history-list").innerHTML = data.items.length
    ? data.items
        .map((item) => {
          const active = app.currentRun?.run_id === item.run_id;
          return `<button class="history-item${active ? " active" : ""}" data-run="${escapeHtml(item.run_id)}"><span class="history-title">${escapeHtml(item.title)}</span><span class="history-meta"><i class="dot${item.status === "completed" ? " green" : ""}"></i>${escapeHtml(labels[item.status] || item.status)}<span>·</span>${escapeHtml(item.started_at ? item.started_at.slice(5, 10) : "刚刚")}</span></button>`;
        })
        .join("")
    : '<p class="muted empty-history">还没有任务记录<br>开始你的第一次代码审查</p>';
}

async function loadRun(runId, refresh = false) {
  clearTimeout(app.poll);
  const generation = refresh ? app.generation : ++app.generation;
  if (!refresh) {
    app.selectedVersion = "latest";
    app.tab = "code";
    app.compare = false;
    app.panelSignature = "";
  }
  try {
    const data = await api(`/api/runs/${encodeURIComponent(runId)}`);
    if (generation !== app.generation) return;
    app.currentRun = data;
    $("welcome").hidden = true;
    $("result").hidden = false;
    document.body.classList.remove("sidebar-open");
    renderRun();
    if (isRunning(data))
      app.poll = setTimeout(() => loadRun(runId, true), 1000);
    else refreshHistory();
  } catch (error) {
    if (generation !== app.generation) return;
    toast(error.message);
    if (refresh) app.poll = setTimeout(() => loadRun(runId, true), 3000);
  }
}

function currentStage(report) {
  if (!isRunning(report)) return null;
  const last = report.history.at(-1)?.stage;
  if (!last || last === "start") return "coder";
  if (last === "coder" || last === "fixer") return "validate";
  if (last === "validate") return "reviewer";
  if (
    last === "reviewer" &&
    (!report.validation?.passed || report.review?.issues.length)
  )
    return "fixer";
  return null;
}

function renderRun() {
  const report = app.currentRun;
  const running = isRunning(report);
  const active = currentStage(report);
  const finishedStages = new Set(report.history.map((event) => event.stage));
  $("result-title").textContent = report.task.requirement;
  $("result-model").textContent =
    `${report.model_name?.startsWith("mock:") ? "离线固定示例" : report.model_name || "正在启动"} · ${report.task.function_name} · ${report.started_at?.slice(0, 10) || "本次任务"}`;
  $("cancel-run").hidden = !running;
  $("cancel-run").disabled = Boolean(report.cancel_requested);
  $("cancel-run").textContent = report.cancel_requested
    ? "停止中…"
    : "停止任务";
  $("reuse-task").disabled = running;
  $("download-all").disabled = !report.code_version;
  const statusText =
    report.cancel_requested && running
      ? "已请求停止，当前步骤结束后会保存已有结果。"
      : running
        ? `${{ coder: "编码 Agent 正在生成代码", validate: "正在运行当前版本的验收", reviewer: "审查 Agent 正在检查代码", fixer: "修复 Agent 正在处理问题" }[active] || "正在整理运行结果"}…`
        : {
            completed: "已完成：当前版本通过固定验收，审查未发现待处理问题。",
            needs_changes:
              "达到修复上限，仍有问题。可以查看审查意见后调整需求或再次运行。",
            failed: report.error || "本次执行未完成，请查看执行记录。",
            cancelled: "任务已停止，已完成的代码与记录已经保留。",
            interrupted: "上次运行因服务关闭而中断，已完成的记录已保留。",
          }[report.status];
  $("run-status").className =
    `run-status${report.status === "failed" ? " error" : ["needs_changes", "interrupted"].includes(report.status) ? " warning" : ""}`;
  $("run-status").innerHTML =
    `${running ? '<span class="status-spinner" aria-hidden="true"></span>' : '<span aria-hidden="true">' + (report.status === "completed" ? "✓" : "◇") + "</span>"}<span>${escapeHtml(statusText)}</span>`;
  $("pipeline").innerHTML = ["coder", "validate", "reviewer", "fixer"]
    .map((stage, index) => {
      const done = finishedStages.has(stage);
      return `${index ? '<span class="pipeline-line"></span>' : ""}<div class="pipeline-step ${active === stage ? "active" : done ? "done" : ""}"><span class="step-icon">${done && active !== stage ? "✓" : index + 1}</span><span>${{ coder: "编码", validate: "验收", reviewer: "审查", fixer: "修复" }[stage]}${stage === "fixer" && report.status === "completed" && !report.repair_count ? " · 无需" : ""}</span></div>`;
    })
    .join("");
  const elapsed = report.started_at
    ? Math.max(
        0,
        Math.floor(
          ((report.finished_at ? new Date(report.finished_at) : Date.now()) -
            new Date(report.started_at)) /
            1000,
        ),
      )
    : 0;
  const passed =
    report.validation?.cases.filter((item) => item.passed).length || 0;
  const total = report.validation?.cases.length || report.task.cases.length;
  $("run-summary").innerHTML =
    `代码版本 <strong>v${report.code_version}</strong><span>修复次数 <strong>${report.repair_count}/${report.max_repairs}</strong></span><span>当前验收 <strong>${report.validation ? `${passed}/${total}` : "待检查"}</strong></span><span>耗时 <strong>${elapsed}s</strong></span>`;
  document
    .querySelectorAll("[data-tab]")
    .forEach((button) =>
      button.setAttribute(
        "aria-selected",
        String(button.dataset.tab === app.tab),
      ),
    );
  const signature = JSON.stringify([
    app.tab,
    app.selectedVersion,
    app.compare,
    report.code_version,
    report.status,
    report.history.length,
    report.versions?.length,
  ]);
  if (app.panelSignature !== signature) {
    app.panelSignature = signature;
    renderPanel();
  }
}

function highlightedLine(source) {
  const pattern =
    /#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b(?:def|return|if|else|elif|for|while|in|not|and|or|is|None|True|False|raise|import|from|as|class|try|except|with|pass|break|continue|lambda)\b|\b\d+(?:\.\d+)?\b/g;
  let result = "",
    offset = 0;
  for (const match of source.matchAll(pattern)) {
    result += escapeHtml(source.slice(offset, match.index));
    const value = match[0];
    const type = value.startsWith("#")
      ? "comment"
      : /^["']/.test(value)
        ? "string"
        : /^\d/.test(value)
          ? "number"
          : "keyword";
    result += `<span class="token-${type}">${escapeHtml(value)}</span>`;
    offset = match.index + value.length;
  }
  return result + escapeHtml(source.slice(offset));
}

function codeHtml(code) {
  const lines = code.replace(/\n$/, "").split("\n");
  const displayed = lines
    .slice(0, 2000)
    .map(
      (line, index) =>
        `<span class="code-line"><span class="line-number" aria-hidden="true">${index + 1}</span>${highlightedLine(line) || " "}</span>`,
    )
    .join("");
  return `<pre class="code-scroll" tabindex="0"><code>${displayed}</code></pre>${lines.length > 2000 ? '<p class="field-help">页面展示前 2000 行，下载包含完整代码。</p>' : ""}`;
}

function selectedCode() {
  const report = app.currentRun;
  if (app.selectedVersion === "latest") return report.code || "";
  return (
    report.versions.find((item) => item.version === Number(app.selectedVersion))
      ?.code ||
    report.code ||
    ""
  );
}

function renderPanel() {
  const report = app.currentRun;
  const panel = $("result-panel");
  const scrolls = [...panel.querySelectorAll(".code-scroll")].map((node) => [
    node.scrollTop,
    node.scrollLeft,
  ]);
  if (app.tab === "code") {
    if (!report.code) {
      panel.innerHTML =
        '<div class="empty-panel">代码团队正在工作。<br>第一版代码生成后会显示在这里。</div>';
      return;
    }
    const code = selectedCode();
    const versions = report.versions || [];
    panel.innerHTML = `<div class="code-box"><div class="code-toolbar"><div class="code-toolbar-left"><span>${escapeHtml(report.task.function_name)}.py</span><select id="version-select" aria-label="选择代码版本"><option value="latest">最新 · v${report.code_version}</option>${versions.map((item) => `<option value="${item.version}" ${String(item.version) === app.selectedVersion ? "selected" : ""}>版本 v${item.version}</option>`).join("")}</select></div><div class="code-toolbar-right"><button id="compare-code" class="text-button" ${versions.length < 2 ? "disabled" : ""}>${app.compare ? "关闭对比" : "对比初版"}</button><button id="copy-code" class="text-button">复制</button><button id="download-code" class="text-button">下载</button></div></div>${app.compare ? `<div class="compare-grid"><div><div class="compare-title">初版 · v1</div>${codeHtml(versions[0]?.code || code)}</div><div><div class="compare-title">所选版本</div>${codeHtml(code)}</div></div>` : codeHtml(code)}</div>`;
    $("version-select").addEventListener("change", (event) => {
      app.selectedVersion = event.target.value;
      app.panelSignature = "";
      renderRun();
    });
    $("compare-code").addEventListener("click", () => {
      app.compare = !app.compare;
      app.panelSignature = "";
      renderRun();
    });
    $("copy-code").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(code);
        toast("代码已复制");
      } catch {
        toast("浏览器未允许复制，请直接选中代码复制");
      }
    });
    $("download-code").addEventListener("click", () =>
      downloadBlob(
        new Blob([code], { type: "text/plain;charset=utf-8" }),
        `${report.task.function_name}.py`,
      ),
    );
  } else if (app.tab === "review") {
    const reviews = report.reviews || [];
    panel.innerHTML = reviews.length
      ? [...reviews]
          .reverse()
          .map(
            (item) =>
              `<section class="review-section"><h3 class="panel-heading"><span class="version-label">v${item.version}</span>${escapeHtml(item.review?.summary || "审查结果")}</h3>${item.review?.issues.length ? item.review.issues.map((issue) => `<article class="review-card"><h3><span class="severity ${escapeHtml(issue.severity)}">${{ high: "高", medium: "中", low: "低" }[issue.severity]}严重度</span>${escapeHtml(issue.message)}${issue.line ? ` · 第 ${issue.line} 行` : ""}</h3><p>证据：${escapeHtml(issue.evidence)}</p><p>建议：${escapeHtml(issue.suggestion)}</p></article>`).join("") : '<div class="review-success">✓ 本轮未发现待处理问题。通过有限检查不代表覆盖所有输入。</div>'}</section>`,
          )
          .join("")
      : '<div class="empty-panel">独立审查完成后，这里会显示具体问题、证据与修复建议。</div>';
  } else if (app.tab === "tests") {
    const validation = report.validation;
    panel.innerHTML = !validation
      ? '<div class="empty-panel">当前版本尚未完成验收，旧版本结论不会沿用。</div>'
      : `<h3 class="panel-heading"><span class="version-label">v${validation.code_version}</span>${escapeHtml(validation.details)}</h3>${validation.cases.length ? `<div class="code-box">${validation.cases.map((test) => `<div class="test-row ${test.passed ? "" : "failed"}"><span class="test-mark">${test.passed ? "✓" : "×"}</span><div><strong>${escapeHtml(test.name)}</strong><p>${escapeHtml(test.detail)}</p></div></div>`).join("")}</div>` : `<div class="inline-error">${escapeHtml(validation.details)}</div>`}`;
  } else {
    panel.innerHTML = `${report.error ? `<div class="inline-error">${escapeHtml(report.error)}</div>` : ""}${report.history.map((event) => `<div class="event-row"><span class="event-time">${escapeHtml(event.time.slice(11, 19))}</span><span class="event-stage">${escapeHtml(stages[event.stage] || event.stage)} · v${event.code_version}</span><span class="event-message">${escapeHtml(event.message)}</span></div>`).join("")}`;
  }
  panel.querySelectorAll(".code-scroll").forEach((node, index) => {
    if (scrolls[index]) {
      node.scrollTop = scrolls[index][0];
      node.scrollLeft = scrolls[index][1];
    }
  });
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function downloadAll() {
  if (!app.currentRun) return;
  try {
    const response = await api(
      `/api/runs/${encodeURIComponent(app.currentRun.run_id)}/download/result.zip`,
      undefined,
      true,
    );
    downloadBlob(await response.blob(), "workflow-result.zip");
  } catch (error) {
    toast(error.message);
  }
}

function bindEvents() {
  $("settings-button").addEventListener("click", showSettings);
  $("mode-button").addEventListener("click", showSettings);
  $("settings-form").addEventListener("submit", saveSettings);
  $("check-connection").addEventListener("click", testConnection);
  $("settings-demo").addEventListener("click", quickDemo);
  $("quick-demo").addEventListener("click", quickDemo);
  $("new-task").addEventListener("click", () => {
    if (app.preparing) toast("请等待当前需求准备完成");
    else newTask();
  });
  $("composer").addEventListener("submit", submitTask);
  $("cases-button").addEventListener("click", showCases);
  $("save-cases").addEventListener("click", saveCases);
  $("add-case").addEventListener("click", addCase);
  $("help-button").addEventListener("click", () => dialog("help-dialog"));
  $("import-task-button").addEventListener("click", () =>
    $("import-task").click(),
  );
  $("import-task").addEventListener("change", importTask);
  $("download-all").addEventListener("click", downloadAll);
  $("menu-button").addEventListener("click", () =>
    document.body.classList.toggle("sidebar-open"),
  );
  $("sidebar-overlay").addEventListener("click", () =>
    document.body.classList.remove("sidebar-open"),
  );
  $("toggle-key").addEventListener("click", () => {
    const visible = $("api-key").type === "password";
    $("api-key").type = visible ? "text" : "password";
    $("toggle-key").textContent = visible ? "隐藏" : "显示";
  });
  $("requirement").addEventListener("input", () => {
    if (app.task && app.task.requirement !== $("requirement").value.trim()) {
      app.task = null;
      app.confirmed = false;
    }
    updateComposer();
  });
  $("provider").addEventListener("change", () => {
    if ($("provider").value === "deepseek") {
      $("base-url").value = defaults.baseUrl;
      $("model-name").value = defaults.model;
    }
    if ($("provider").value === "local") {
      $("base-url").value = "http://localhost:11434/v1";
      $("model-name").value = "";
    }
    renderSettingsMode();
  });
  document.querySelectorAll("[data-mode]").forEach((button) =>
    button.addEventListener("click", () => {
      app.settingsMode = button.dataset.mode;
      renderSettingsMode();
    }),
  );
  document
    .querySelectorAll(".close-dialog")
    .forEach((button) =>
      button.addEventListener("click", () => button.closest("dialog").close()),
    );
  $("history-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-run]");
    if (button) loadRun(button.dataset.run);
  });
  $("case-editor").addEventListener("click", (event) => {
    if (event.target.closest(".case-delete"))
      event.target.closest(".case-row").remove();
  });
  $("case-editor").addEventListener("change", (event) => {
    if (event.target.dataset.field === "type") {
      const row = event.target.closest(".case-row");
      row.querySelector("[data-expected]").hidden =
        event.target.value !== "expected";
      row.querySelector("[data-raises]").hidden =
        event.target.value !== "raises";
    }
  });
  document.querySelectorAll("[data-tab]").forEach((button) =>
    button.addEventListener("click", () => {
      app.tab = button.dataset.tab;
      renderRun();
    }),
  );
  $("cancel-run").addEventListener("click", async () => {
    try {
      const data = await api(`/api/runs/${app.currentRun.run_id}/cancel`, {});
      toast(data.message);
      loadRun(app.currentRun.run_id, true);
    } catch (error) {
      toast(error.message);
    }
  });
  $("reuse-task").addEventListener("click", () => {
    const task = structuredClone(app.currentRun.task);
    const repairs = app.currentRun.max_repairs;
    loadExample(task);
    app.maxRepairs = repairs;
  });
  document.addEventListener("keydown", (event) => {
    if (
      (event.ctrlKey || event.metaKey) &&
      event.key === "Enter" &&
      !$("welcome").hidden &&
      !document.querySelector("dialog[open]")
    ) {
      event.preventDefault();
      $("composer").requestSubmit();
    }
  });
}

async function initialize() {
  bindEvents();
  renderConfig();
  try {
    const data = await api("/api/bootstrap");
    app.examples = data.examples;
    const titles = {
      average: ["x̄", "平均值计算", "空列表 · 小数 · 边界"],
      deduplicate: ["↻", "列表去重", "顺序保持 · 输入不变"],
      factorial: ["n!", "阶乘函数", "异常处理 · 类型检查"],
    };
    $("example-list").innerHTML = app.examples
      .map((task) => {
        const item = titles[task.id] || ["⌘", task.function_name, "内置任务"];
        return `<button class="example-button" data-example="${escapeHtml(task.id)}"><span class="example-icon">${item[0]}</span><span><strong>${item[1]}</strong><small>${item[2]}</small></span></button>`;
      })
      .join("");
    $("example-list").addEventListener("click", (event) => {
      const button = event.target.closest("[data-example]");
      if (button && !app.preparing)
        loadExample(
          app.examples.find((task) => task.id === button.dataset.example),
        );
    });
    renderHistory(data.history);
    if (data.history.active_run) await loadRun(data.history.active_run);
    else if (!configured()) showSettings();
    setInterval(() => {
      if (!document.hidden) refreshHistory();
    }, 6000);
  } catch (error) {
    toast(error.message);
  }
}

initialize();
