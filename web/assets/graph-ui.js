"use strict";

// 画布保存配置；实际执行、类型校验与跳转全部由后端负责。
window.workflowEditor = (() => {
  const titles = {
    start: "开始",
    coder: "编码 Agent",
    validate: "验收工具",
    reviewer: "发现者 Agent",
    verifier: "验证者 Agent",
    fixer: "修复 Agent",
    custom: "自定义 Agent",
    gate: "程序判定",
    end: "完成",
  };
  const inputTitles = {
    task: "原始任务与固定验收",
    code: "当前源码",
    validation: "当前验收结果",
    review: "候选审查问题",
    verification: "问题验证结果",
    upstream: "上游节点输出（必选）",
  };
  const descriptions = {
    start: "固定本次任务与流程快照。",
    coder: "生成代码，读取原始任务与直接上游建议。",
    validate: "真实执行固定验收，不由模型决定通过。",
    reviewer: "提出有证据的候选问题。",
    verifier: "独立核对候选问题，输出确认、驳回或待确认。",
    fixer: "处理已确认问题及验收失败，生成新版本。",
    custom: "分析所选信息，输出结论和建议，传递给下一个节点。",
    gate: "验收失败或确认问题进入修复；仅剩待确认问题时暂停；全部通过后完成。",
    end: "记录最终状态，不能绕过验收或待处理问题。",
  };
  const clone = (value) => structuredClone(value);
  let active = null,
    draft = null,
    libraryId = null,
    activeId = null;
  let selectedNode = null,
    selectedEdge = -1,
    linkSource = null,
    undo = [];
  let templates = [],
    library = [],
    previousView = "welcome",
    ready = false;
  let editorZoom = 1;
  let rolePrompts = {};
  let loadError = "";
  let inspectedRunNode = null,
    inspectedVisit = null;

  function feedback(message, error = false) {
    $("graph-feedback").textContent = message;
    $("graph-feedback").classList.toggle("error", error);
  }
  function remember() {
    undo.push(clone(draft));
    if (undo.length > 30) undo.shift();
    $("graph-dirty").textContent = "画布有未保存修改";
  }
  function updateChoice() {
    $("workflow-choice").textContent =
      `◇ 当前流程：${active?.name || "默认三角色"} · 编辑流程 ↗`;
  }
  function use(definition, identifier = null) {
    active = clone(definition);
    activeId = identifier;
    updateChoice();
    try {
      localStorage.setItem(
        "workflow.graph.v1",
        JSON.stringify({ id: identifier, definition: active }),
      );
    } catch {
      /* 不影响本次使用。 */
    }
  }
  function open() {
    if (!ready) {
      toast(loadError || "流程正在载入，请稍后重试");
      return;
    }
    previousView = $("result").hidden ? "welcome" : "result";
    $("welcome").hidden = true;
    $("result").hidden = true;
    $("graph-workspace").hidden = false;
    document.body.classList.remove("sidebar-open");
    if (!draft) loadDraft(active, activeId);
    else render();
  }
  function close() {
    $("graph-workspace").hidden = true;
    $(previousView).hidden = false;
  }
  function loadDraft(definition, identifier = null) {
    draft = clone(definition);
    libraryId = identifier;
    selectedNode = null;
    selectedEdge = -1;
    linkSource = null;
    undo = [];
    $("graph-name").value = draft.name;
    $("graph-dirty").textContent = "载入后可编辑，保存后用于新任务";
    feedback("选择节点查看职责，选择连线可在该位置插入角色。");
    render();
  }
  function setEditorZoom(value) {
    editorZoom = Math.max(0.35, Math.min(1.5, Number(value) || 1));
    const select = $("graph-zoom");
    select.querySelector("[data-fit-scale]")?.remove();
    if (
      ![...select.options].some((option) => Number(option.value) === editorZoom)
    ) {
      const option = document.createElement("option");
      option.value = String(editorZoom);
      option.textContent = `${Math.round(editorZoom * 100)}%（适应结果）`;
      option.dataset.fitScale = "true";
      select.append(option);
    }
    select.value = String(editorZoom);
    render();
  }
  function graphSize(definition) {
    return {
      width: Math.max(1060, ...definition.nodes.map((n) => n.x + 250)),
      height: Math.max(680, ...definition.nodes.map((n) => n.y + 180)),
    };
  }
  function paintEdges(svg, definition, options = {}) {
    const ns = "http://www.w3.org/2000/svg",
      size = graphSize(definition);
    svg.replaceChildren();
    const markerId = options.readonly ? "run-arrow" : "edit-arrow";
    svg.innerHTML = `<defs><marker id="${markerId}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#7d9687"/></marker></defs>`;
    definition.edges.forEach((edge, index) => {
      const from = definition.nodes.find((n) => n.id === edge.source),
        to = definition.nodes.find((n) => n.id === edge.target);
      if (!from || !to) return;
      const route = GraphView.edgePath(from, to, edge.condition, size);
      const line = document.createElementNS(ns, "path");
      line.setAttribute("d", route);
      line.setAttribute(
        "class",
        `graph-edge ${edge.condition}${!options.readonly && selectedEdge === index ? " selected" : ""}`,
      );
      line.setAttribute("marker-end", `url(#${markerId})`);
      svg.append(line);
      if (!options.readonly) {
        const hit = document.createElementNS(ns, "path");
        hit.setAttribute("d", route);
        hit.setAttribute("class", "edge-hit");
        hit.addEventListener("click", () => {
          selectedEdge = index;
          selectedNode = null;
          linkSource = null;
          render();
          feedback("连线已选中。右侧已载入起点、出口与终点，可直接调整。");
        });
        svg.append(hit);
      }
    });
  }

  function draw(canvas, definition, options = {}) {
    canvas.replaceChildren();
    GraphView.mount(
      canvas,
      graphSize(definition),
      options.readonly ? 1 : editorZoom,
    );
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "graph-edges");
    paintEdges(svg, definition, options);
    canvas.append(svg);
    definition.nodes.forEach((node) => {
      const runs =
        options.report?.node_runs?.filter((r) => r.node_id === node.id) || [];
      const status = runs.at(-1)?.status || "pending";
      const card = document.createElement("div");
      card.dataset.nodeId = node.id;
      card.className = `flow-node ${node.kind} ${options.readonly ? status : ""} ${(options.readonly ? inspectedRunNode : selectedNode) === node.id ? "selected" : ""}`;
      card.style.left = `${node.x}px`;
      card.style.top = `${node.y}px`;
      const head = document.createElement("button");
      head.className = "flow-node-head";
      head.textContent = node.name;
      head.title = node.name;
      head.setAttribute(
        "aria-label",
        `${options.readonly ? "查看" : "选择"}节点 ${node.name}`,
      );
      head.addEventListener("click", () => {
        if (options.readonly) {
          inspectedRunNode = node.id;
          inspectedVisit = null;
          options.onSelect(node.id);
        } else if (
          linkSource &&
          linkSource.id !== node.id &&
          node.kind !== "start"
        )
          connectTarget(node.id);
        else {
          selectedNode = node.id;
          selectedEdge = -1;
          render();
        }
      });
      card.append(head);
      const type = document.createElement("span");
      type.className = "flow-node-type";
      type.textContent = titles[node.kind];
      card.append(type);
      if (options.readonly) {
        const meta = document.createElement("div");
        meta.className = "flow-node-meta";
        meta.textContent = `${{ pending: "未执行", running: "运行中", completed: "已完成", failed: "失败", cancelled: "已停止" }[status] || status} · ${runs.length} 次`;
        card.append(meta);
      } else {
        const ports = document.createElement("div");
        ports.className = "node-ports";
        if (node.kind !== "start")
          ports.append(
            port("input", "always", `连接到 ${node.name}`, () =>
              connectTarget(node.id),
            ),
          );
        const exits =
          node.kind === "gate"
            ? ["pass", "repair"]
            : node.kind === "end"
              ? []
              : ["always"];
        exits.forEach((condition) => {
          const output = port(
            "output",
            condition,
            `从 ${node.name} ${condition} 连线`,
            () => beginLink(node, condition),
          );
          bindConnectionDrag(output, node, condition, canvas, svg);
          ports.append(output);
          const caption = document.createElement("span");
          caption.className = `port-caption ${condition}`;
          caption.textContent =
            condition === "pass"
              ? "通过"
              : condition === "repair"
                ? "需修复"
                : "下一步";
          ports.append(caption);
        });
        card.append(ports);
        bindDrag(head, card, node, () => paintEdges(svg, definition));
      }
      if (!options.readonly)
        card.addEventListener("click", (event) => {
          if (
            linkSource &&
            node.id !== linkSource.id &&
            node.kind !== "start" &&
            !event.target.closest("button")
          )
            connectTarget(node.id);
        });
      canvas.append(card);
    });
    if (!options.readonly) markConnectionTargets(canvas);
  }

  function port(side, condition, aria, action) {
    const button = document.createElement("button");
    button.className = `node-port ${side} ${condition}`;
    button.setAttribute("aria-label", aria);
    button.title = aria;
    button.dataset.portSide = side;
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      if (button.dataset.skipClick) {
        delete button.dataset.skipClick;
        return;
      }
      action();
    });
    return button;
  }
  function beginLink(node, condition) {
    linkSource = { id: node.id, condition };
    selectedNode = node.id;
    selectedEdge = -1;
    render();
    feedback(
      `从「${node.name}」连接：点击高亮入口或目标卡片。按 Esc 或“取消连线”退出。`,
    );
  }
  function cancelLink() {
    linkSource = null;
    render();
    feedback("已取消连线，原有连接保持不变。");
  }
  function markConnectionTargets(canvas) {
    $("cancel-connection").hidden = !linkSource;
    canvas.classList.toggle("connecting", Boolean(linkSource));
    canvas.querySelectorAll(".flow-node").forEach((card) => {
      const node = draft.nodes.find((n) => n.id === card.dataset.nodeId);
      card.classList.toggle(
        "connection-target",
        Boolean(
          linkSource && node.kind !== "start" && node.id !== linkSource.id,
        ),
      );
      card
        .querySelectorAll(".node-port.output")
        .forEach((button) =>
          button.classList.toggle(
            "source-active",
            Boolean(
              linkSource?.id === node.id &&
              button.classList.contains(linkSource.condition),
            ),
          ),
        );
    });
  }
  function bindConnectionDrag(button, node, condition, canvas, svg) {
    let drag = null,
      preview = null;
    button.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      drag = { x: event.clientX, y: event.clientY, moved: false };
      button.setPointerCapture(event.pointerId);
    });
    button.addEventListener("pointermove", (event) => {
      if (!drag) return;
      if (
        Math.abs(event.clientX - drag.x) + Math.abs(event.clientY - drag.y) <
          5 &&
        !drag.moved
      )
        return;
      drag.moved = true;
      linkSource = { id: node.id, condition };
      markConnectionTargets(canvas);
      if (!preview) {
        preview = document.createElementNS(
          "http://www.w3.org/2000/svg",
          "path",
        );
        preview.setAttribute("class", "connection-preview");
        svg.append(preview);
      }
      const rect = canvas.getBoundingClientRect(),
        scale = GraphView.scale(canvas);
      const a = GraphView.anchor(node, "output", condition),
        x = (event.clientX - rect.left) / scale,
        y = (event.clientY - rect.top) / scale;
      preview.setAttribute(
        "d",
        `M${a.x},${a.y} C${a.x + 70},${a.y} ${x - 70},${y} ${x},${y}`,
      );
    });
    button.addEventListener("pointerup", (event) => {
      if (!drag?.moved) {
        drag = null;
        return;
      }
      button.dataset.skipClick = "1";
      preview?.remove();
      preview = null;
      drag = null;
      const target = document
        .elementFromPoint(event.clientX, event.clientY)
        ?.closest(".flow-node");
      if (
        target &&
        target.dataset.nodeId !== node.id &&
        !target.classList.contains("start")
      )
        connectTarget(target.dataset.nodeId);
      else {
        render();
        feedback("选择一个高亮入口或目标卡片完成连线，也可按 Esc 取消。");
      }
    });
    button.addEventListener("pointercancel", () => {
      drag = null;
      preview?.remove();
      preview = null;
      linkSource = null;
      render();
    });
  }
  function bindDrag(head, card, node, updateEdges) {
    let drag = null;
    head.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      drag = {
        x: event.clientX,
        y: event.clientY,
        nx: node.x,
        ny: node.y,
        moved: false,
      };
      head.setPointerCapture(event.pointerId);
    });
    head.addEventListener("pointermove", (event) => {
      if (!drag) return;
      const scale = GraphView.scale(card.parentElement);
      const dx = (event.clientX - drag.x) / scale,
        dy = (event.clientY - drag.y) / scale;
      if (!drag.moved && Math.abs(dx) + Math.abs(dy) > 5) {
        remember();
        drag.moved = true;
      }
      if (!drag.moved) return;
      node.x = Math.max(10, Math.min(4000, drag.nx + dx));
      node.y = Math.max(10, Math.min(3000, drag.ny + dy));
      card.style.left = `${node.x}px`;
      card.style.top = `${node.y}px`;
      updateEdges();
    });
    head.addEventListener("pointerup", () => {
      if (drag?.moved) {
        selectedNode = node.id;
        selectedEdge = -1;
        render();
      }
      drag = null;
    });
    head.addEventListener("pointercancel", () => {
      drag = null;
      render();
    });
  }
  function render() {
    if (!draft) return;
    draw($("graph-canvas"), draft);
    $("graph-undo").disabled = !undo.length;
    $("add-verifier").disabled = draft.nodes.some((n) => n.kind === "verifier");
    renderInspector();
  }
  function renderInspector() {
    const node = draft.nodes.find((n) => n.id === selectedNode),
      edge = draft.edges[selectedEdge];
    let html =
      '<h3>节点与连线</h3><p class="field-help">自定义角色可以放在主路径、修复路径或完成前。核心节点保留明确的输入输出与顺序约束。</p>';
    if (node) {
      html = `<h3>${escapeHtml(titles[node.kind])}</h3><label>角色名称<input id="node-name" maxlength="60" value="${escapeHtml(node.name)}"></label><label>角色说明<textarea id="node-description" class="role-description" maxlength="2000">${escapeHtml(node.description || descriptions[node.kind])}</textarea></label>`;
      if (node.kind === "custom") {
        html += `<label>自定义 Prompt（发送给模型）<textarea id="node-prompt" maxlength="6000" placeholder="写清角色职责、分析步骤、证据要求和建议…">${escapeHtml(node.prompt)}</textarea></label><p class="field-help">这才是自定义提示词，支持完整编辑。名称和说明单独保存；系统另加统一 JSON 输出约束。</p><details class="prompt-details"><summary>查看系统输出约束</summary><pre>${escapeHtml(rolePrompts.custom)}</pre></details>`;
      } else if (rolePrompts[node.kind]) {
        html += `<details class="prompt-details" open><summary>内置系统 Prompt（已启用，只读）</summary><textarea class="base-prompt" aria-label="内置系统 Prompt" readonly>${escapeHtml(rolePrompts[node.kind])}</textarea></details><label>补充 Prompt（可选）<textarea id="node-prompt" maxlength="6000" placeholder="例如：额外关注输入边界或算法复杂度。留空仍使用完整内置 Prompt。">${escapeHtml(node.prompt)}</textarea></label><p class="field-help">内置提示词始终启用。补充框只填写额外要求，留空不会取消默认 Prompt。</p>`;
      } else {
        html +=
          '<p class="graph-feedback">这是程序控制或验收工具节点，不调用大模型，因此没有 Prompt。</p>';
      }
      if (node.kind === "custom")
        html += `<p class="field-help">读取的信息（尚未产生的信息会在结构检查时阻止）：</p>${Object.entries(
          inputTitles,
        )
          .map(
            ([key, label]) =>
              `<label class="input-check"><input type="checkbox" data-node-input="${key}" ${node.inputs.includes(key) ? "checked" : ""} ${key === "upstream" ? "disabled" : ""}>${label}</label>`,
          )
          .join("")}`;
      html +=
        '<button id="apply-node" class="secondary-button">应用节点设置</button>';
      if (["custom", "verifier"].includes(node.kind))
        html +=
          '<button id="remove-node" class="danger-link">删除此角色并尝试接回连线</button>';
    } else if (edge) {
      html = `<h3>已选中连线</h3><p class="field-help">${escapeHtml(draft.nodes.find((n) => n.id === edge.source)?.name)} → ${escapeHtml(draft.nodes.find((n) => n.id === edge.target)?.name)}</p><p class="field-help">现在点击“＋ 自定义角色”会自动插入这条连线。</p><button id="remove-edge" class="danger-link">删除此连线</button>`;
    }
    const choices = draft.nodes
      .filter((n) => n.kind !== "end")
      .map((n) => `<option value="${n.id}">${escapeHtml(n.name)}</option>`)
      .join("");
    html += `<hr><h3>连接设置</h3><label>起点<select id="edge-source">${choices}</select></label><label>出口<select id="edge-condition"></select></label><label>终点<select id="edge-target"></select></label><button id="connect-edge" class="secondary-button">${edge ? "更新这条连线" : "连接节点"}</button><p class="field-help">选中现有连线可直接调整。每个出口只保留一个目标，连接完成后点“检查结构”。</p><label>总步数上限<input id="graph-max-steps" type="number" min="10" max="300" value="${draft.max_steps}"></label><button id="apply-limit" class="secondary-button">应用步数上限</button>`;
    $("graph-inspector").innerHTML = html;
    if (node) {
      $("edge-source").value = node.id;
      $("apply-node").onclick = () => {
        remember();
        node.name = $("node-name").value.trim();
        node.description = $("node-description").value.trim();
        if ($("node-prompt")) node.prompt = $("node-prompt").value.trim();
        if (node.kind === "custom")
          node.inputs = [
            ...document.querySelectorAll("[data-node-input]:checked"),
          ].map((e) => e.dataset.nodeInput);
        render();
        feedback("节点设置已应用到画布，请检查结构后保存。");
      };
    }
    if ($("remove-node")) $("remove-node").onclick = removeNode;
    if ($("remove-edge"))
      $("remove-edge").onclick = () => {
        remember();
        draft.edges.splice(selectedEdge, 1);
        selectedEdge = -1;
        render();
        feedback("连线已删除。重新连接后再保存。");
      };
    $("connect-edge").onclick = () =>
      connect(
        $("edge-source").value,
        $("edge-target").value,
        $("edge-condition").value,
      );
    $("apply-limit").onclick = () => {
      const n = Number($("graph-max-steps").value);
      if (!Number.isInteger(n) || n < 10 || n > 300) {
        feedback("步数上限必须为 10 至 300 的整数", true);
        return;
      }
      remember();
      draft.max_steps = n;
      feedback("步数上限已更新。");
    };
    const selectedSource =
      edge?.source ||
      (node?.kind !== "end" ? node?.id : null) ||
      draft.nodes.find((n) => n.kind === "start").id;
    $("edge-source").value = selectedSource;
    function updateConnectionFields(preferredCondition, preferredTarget) {
      const from = draft.nodes.find((n) => n.id === $("edge-source").value);
      const conditions = from.kind === "gate" ? ["pass", "repair"] : ["always"];
      $("edge-condition").innerHTML = conditions
        .map(
          (value) =>
            `<option value="${value}">${{ always: "下一步", pass: "通过", repair: "需修复" }[value]}</option>`,
        )
        .join("");
      if (conditions.includes(preferredCondition))
        $("edge-condition").value = preferredCondition;
      updateTarget(preferredTarget);
    }
    function updateTarget(preferredTarget) {
      const from = $("edge-source").value,
        condition = $("edge-condition").value;
      const current = draft.edges.find(
        (e) => e.source === from && e.condition === condition,
      );
      $("edge-target").innerHTML =
        '<option value="">选择目标节点</option>' +
        draft.nodes
          .filter((n) => n.kind !== "start" && n.id !== from)
          .map((n) => `<option value="${n.id}">${escapeHtml(n.name)}</option>`)
          .join("");
      $("edge-target").value = preferredTarget || current?.target || "";
    }
    $("edge-source").onchange = () => updateConnectionFields();
    $("edge-condition").onchange = () => updateTarget();
    updateConnectionFields(edge?.condition, edge?.target);
  }
  function connect(source, target, condition) {
    const node = draft.nodes.find((n) => n.id === source);
    if (!node || !draft.nodes.some((n) => n.id === target)) {
      feedback("请选择有效的起点与终点。", true);
      return;
    }
    if (
      source === target ||
      node.kind === "end" ||
      draft.nodes.find((n) => n.id === target)?.kind === "start"
    ) {
      feedback("不能连接自身、从完成节点出发，或连接到开始节点。", true);
      return;
    }
    if ((node.kind === "gate") === (condition === "always")) {
      feedback("判定节点使用通过/修复出口，其他节点使用普通出口。", true);
      return;
    }
    remember();
    draft.edges = draft.edges.filter(
      (e) => !(e.source === source && e.condition === condition),
    );
    draft.edges.push({ source, target, condition });
    selectedEdge = draft.edges.length - 1;
    selectedNode = null;
    linkSource = null;
    render();
    feedback("连线已更新，请检查整体结构。");
  }
  function connectTarget(target) {
    if (!linkSource) {
      selectedNode = target;
      selectedEdge = draft.edges.findIndex((edge) => edge.target === target);
      render();
      feedback("先点击起点节点的出口，再点击目标入口。");
      return;
    }
    connect(linkSource.id, target, linkSource.condition);
  }
  function addNode(kind) {
    if (draft.nodes.length >= 24) {
      feedback("最多支持 24 个节点", true);
      return;
    }
    if (kind === "verifier" && draft.nodes.some((n) => n.kind === kind)) return;
    remember();
    let index = selectedEdge;
    if (kind === "verifier")
      index = draft.edges.findIndex(
        (e) => draft.nodes.find((n) => n.id === e.source)?.kind === "reviewer",
      );
    if (index < 0)
      index = draft.edges.findIndex(
        (e) =>
          e.source === (selectedNode || "coder") && e.condition === "always",
      );
    const edge = draft.edges[index],
      source = draft.nodes.find((n) => n.id === edge?.source);
    const node = {
      id: `${kind}_${crypto.randomUUID().slice(0, 8)}`,
      kind,
      name: kind === "verifier" ? "问题验证者" : "自定义分析员",
      description: descriptions[kind],
      prompt:
        kind === "custom"
          ? "分析上游输出，对照原始任务给出具体建议；说明依据与不确定之处。"
          : "",
      inputs: ["task", "upstream"],
      x: Math.min(4000, (source?.x || 80) + 40),
      y: Math.min(3000, (source?.y || 80) + 160),
    };
    draft.nodes.push(node);
    if (edge) {
      draft.edges.splice(
        index,
        1,
        { source: edge.source, target: node.id, condition: edge.condition },
        { source: node.id, target: edge.target, condition: "always" },
      );
    }
    selectedNode = node.id;
    selectedEdge = -1;
    render();
    feedback(
      edge
        ? "角色已插入所选路径，请配置职责与读取信息。"
        : "角色已添加，请手动接入流程。",
    );
  }
  function removeNode() {
    const node = draft.nodes.find((n) => n.id === selectedNode);
    if (!node || !["custom", "verifier"].includes(node.kind)) return;
    remember();
    const incoming = draft.edges.filter((e) => e.target === node.id),
      outgoing = draft.edges.filter((e) => e.source === node.id);
    draft.edges = draft.edges.filter(
      (e) => e.target !== node.id && e.source !== node.id,
    );
    if (incoming.length === 1 && outgoing.length === 1)
      draft.edges.push({ ...incoming[0], target: outgoing[0].target });
    draft.nodes = draft.nodes.filter((n) => n.id !== node.id);
    selectedNode = null;
    render();
    feedback("角色已删除，请检查结构。");
  }
  function layout() {
    remember();
    const main = [],
      visited = new Set();
    let current = draft.nodes.find((n) => n.kind === "start")?.id;
    while (current && !visited.has(current)) {
      visited.add(current);
      main.push(current);
      const n = draft.nodes.find((n) => n.id === current);
      current = draft.edges.find(
        (e) =>
          e.source === current &&
          e.condition === (n?.kind === "gate" ? "pass" : "always"),
      )?.target;
    }
    const rest = draft.nodes.filter((n) => !visited.has(n.id)).map((n) => n.id);
    [...main, ...rest].forEach((id, i) => {
      const node = draft.nodes.find((n) => n.id === id);
      const row = Math.floor(i / 4),
        col = row % 2 ? 3 - (i % 4) : i % 4;
      node.x = 45 + col * 250;
      node.y = 50 + row * 190;
    });
    render();
  }
  async function check() {
    try {
      const result = await api("/api/workflows/validate", draft);
      feedback(result.message);
      return result.definition;
    } catch (error) {
      feedback(error.message, true);
      return null;
    }
  }
  async function save() {
    $("save-workflow").disabled = true;
    try {
      draft.name = $("graph-name").value.trim();
      const result = await api("/api/workflows/save", {
        id: libraryId,
        definition: draft,
      });
      libraryId = result.id;
      use(result.definition, result.id);
      draft = clone(result.definition);
      render();
      $("graph-dirty").textContent = "已保存 · 用于后续新任务";
      feedback("流程已保存并设为当前流程。正在运行的任务继续使用原快照。");
      await refreshLibrary();
    } catch (error) {
      feedback(error.message, true);
    } finally {
      $("save-workflow").disabled = false;
    }
  }
  async function refreshLibrary() {
    library = (await api("/api/workflows")).items;
    $("graph-library").innerHTML =
      '<option value="">选择模板或已保存流程</option>' +
      templates
        .map(
          (g, i) =>
            `<option value="template:${i}">模板 · ${escapeHtml(g.name)}</option>`,
        )
        .join("") +
      library
        .map(
          (g) =>
            `<option value="${g.id}">已保存 · ${escapeHtml(g.definition.name)}</option>`,
        )
        .join("");
  }
  function renderReport(report) {
    const panel = $("result-panel");
    if (!report.workflow) {
      panel.innerHTML =
        '<div class="empty-panel">此历史任务使用旧版固定流程，没有保存流程图。</div>';
      return;
    }
    const previousScroll = panel.querySelector(".graph-scroll");
    const scroll = [
      previousScroll?.scrollLeft || 0,
      previousScroll?.scrollTop || 0,
    ];
    panel.innerHTML =
      '<div class="graph-run-layout"><div class="graph-scroll"><div class="graph-canvas" id="run-graph-canvas"></div></div><aside class="graph-run-inspector" id="run-graph-inspector"></aside></div>';
    const select = () => {
      const node =
        report.workflow.nodes.find((n) => n.id === inspectedRunNode) ||
        report.workflow.nodes.find((n) => n.id === report.current_node) ||
        report.workflow.nodes[0];
      inspectedRunNode = node.id;
      const runs = (report.node_runs || []).filter(
        (r) => r.node_id === node.id,
      );
      const index =
        inspectedVisit === null
          ? runs.length - 1
          : Math.min(inspectedVisit, runs.length - 1);
      const record = runs[index];
      $("run-graph-inspector").innerHTML =
        `<h3>${escapeHtml(node.name)}</h3><p class="field-help">${escapeHtml(descriptions[node.kind])}</p>${runs.length ? `<select id="node-visit" aria-label="查看节点执行轮次">${runs.map((r, i) => `<option value="${i}" ${i === index ? "selected" : ""}>第 ${i + 1} 次 · v${r.code_version} · ${{ running: "运行中", completed: "完成", failed: "失败", cancelled: "停止" }[r.status] || r.status}</option>`).join("")}</select><p class="field-help">读取信息 / 版本</p><pre>${escapeHtml(JSON.stringify(record.input, null, 2))}</pre><p class="field-help">输出${record.error ? " / 错误" : ""}</p><pre>${escapeHtml(JSON.stringify(record.output || record.error || "正在执行…", null, 2))}</pre>` : '<p class="field-help">此节点尚未执行，可能属于未走到的分支。</p>'}`;
      if ($("node-visit"))
        $("node-visit").onchange = () => {
          inspectedVisit = Number($("node-visit").value);
          select();
        };
      draw($("run-graph-canvas"), report.workflow, {
        readonly: true,
        report,
        onSelect: select,
      });
    };
    select();
    const container = panel.querySelector(".graph-scroll");
    container.scrollLeft = scroll[0];
    container.scrollTop = scroll[1];
  }
  function renderVerification(report) {
    const runs = (report.node_runs || []).filter(
      (r) => r.kind === "verifier" && r.output,
    );
    $("result-panel").innerHTML = runs.length
      ? [...runs]
          .reverse()
          .map(
            (r) =>
              `<section class="review-section"><h3 class="panel-heading">v${r.code_version} · ${escapeHtml(r.output.summary)}</h3>${r.output.findings.length ? r.output.findings.map((f) => `<article class="verification-card"><h4><span class="verdict ${f.verdict}">${{ confirmed: "已确认", rejected: "已驳回", uncertain: "待确认" }[f.verdict]}</span>${escapeHtml(f.id)} · ${escapeHtml(f.issue.message)}</h4><p>${escapeHtml(f.reason)}</p>${f.source_quote ? `<blockquote>${escapeHtml(f.source_quote)}</blockquote>` : ""}<p class="field-help">源码引用：${f.quote_exists ? "存在" : "未核实"} · 对应 v${r.code_version} · ${f.issue.line ? `第 ${f.issue.line} 行` : "未定位行号"}</p></article>`).join("") : '<div class="review-success">无候选问题；没有额外调用验证模型。程序验收仍独立生效。</div>'}</section>`,
          )
          .join("")
      : '<div class="empty-panel">当前流程未加入验证者，或该节点尚未运行。可在工作流设计器加入“问题验证者”。</div>';
  }
  async function init() {
    $("open-workflows").onclick = open;
    $("workflow-choice").onclick = open;
    $("close-workflows").onclick = close;
    $("add-custom").onclick = () => addNode("custom");
    $("add-verifier").onclick = () => addNode("verifier");
    $("graph-layout").onclick = layout;
    $("graph-zoom").onchange = () =>
      setEditorZoom(Number($("graph-zoom").value));
    $("graph-fit").onclick = () => {
      const width = $("graph-scroll").clientWidth;
      setEditorZoom(GraphView.fitScale(width, graphSize(draft).width));
    };
    $("cancel-connection").onclick = cancelLink;
    document.addEventListener("keydown", (event) => {
      if (
        event.key === "Escape" &&
        linkSource &&
        !document.querySelector("dialog[open]") &&
        !$("graph-workspace").hidden
      ) {
        event.preventDefault();
        cancelLink();
      }
    });
    $("check-workflow").onclick = check;
    $("save-workflow").onclick = save;
    $("graph-undo").onclick = () => {
      if (!undo.length) return;
      draft = undo.pop();
      selectedNode = null;
      selectedEdge = -1;
      $("graph-name").value = draft.name;
      render();
      feedback("已撤销上一次画布修改。");
    };
    $("graph-name").onchange = () => {
      remember();
      draft.name = $("graph-name").value.trim();
    };
    $("graph-library").onchange = () => {
      const value = $("graph-library").value;
      if (value.startsWith("template:"))
        loadDraft(templates[Number(value.split(":")[1])]);
      else {
        const entry = library.find((g) => g.id === value);
        if (entry) loadDraft(entry.definition, entry.id);
      }
    };
    $("export-workflow").onclick = () =>
      downloadBlob(
        new Blob([JSON.stringify(draft, null, 2)], {
          type: "application/json",
        }),
        "workflow.json",
      );
    $("import-workflow-button").onclick = () => $("import-workflow").click();
    $("import-workflow").onchange = async (event) => {
      const file = event.target.files[0];
      if (!file) return;
      try {
        if (file.size > 256000) throw new Error("流程文件不能超过 256 KB");
        const result = await api(
          "/api/workflows/validate",
          JSON.parse(await file.text()),
        );
        loadDraft(result.definition);
        feedback("流程已导入，请保存后使用。");
      } catch (error) {
        feedback(error.message, true);
      } finally {
        event.target.value = "";
      }
    };
    $("new-task").addEventListener("click", () => {
      $("graph-workspace").hidden = true;
    });
    $("history-list").addEventListener("click", (event) => {
      if (event.target.closest("[data-run]"))
        $("graph-workspace").hidden = true;
    });
    try {
      const data = await api("/api/bootstrap");
      if (!data.role_prompts)
        throw new Error(
          "后台仍是旧版本，请关闭原启动窗口并重新双击 start.bat。",
        );
      rolePrompts = data.role_prompts;
      templates = data.workflow_templates;
      let stored = null;
      try {
        stored = JSON.parse(localStorage.getItem("workflow.graph.v1"));
      } catch {
        /* 使用默认模板。 */
      }
      if (stored?.definition) {
        try {
          const validated = await api(
            "/api/workflows/validate",
            stored.definition,
          );
          use(validated.definition, stored.id);
        } catch {
          use(templates[0]);
        }
      } else use(templates[0]);
      await refreshLibrary();
      ready = true;
      loadDraft(active, activeId);
    } catch (error) {
      feedback(error.message, true);
      loadError = error.message;
      toast(loadError);
    }
  }
  init();
  return {
    definition: () => (active ? clone(active) : null),
    renderReport,
    renderVerification,
    open,
    restore: (definition) => {
      if (definition) {
        use(definition);
        draft = null;
      }
    },
  };
})();
