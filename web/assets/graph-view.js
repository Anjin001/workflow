"use strict";

// 缩放只作用于画布内容，滚动容器始终使用未缩放的尺寸。
(function (root) {
  const views = new WeakMap();
  const NODE_WIDTH = 190;

  function fitScale(width, contentWidth) {
    return Math.max(
      0.35,
      Math.min(1, (Math.max(1, width) - 24) / contentWidth),
    );
  }

  function mount(canvas, size, requestedScale = 1) {
    let view = views.get(canvas);
    if (!view) {
      const viewport = canvas.parentElement;
      const surface = canvas.ownerDocument.createElement("div");
      surface.className = "graph-surface";
      viewport.replaceChild(surface, canvas);
      surface.append(canvas);
      view = { surface, scale: 1 };
      views.set(canvas, view);
    }
    // 此处只消费用户指定的数值，不观察布局、不测量可用宽度、不自动适配。
    view.scale = Math.max(0.35, Math.min(1.5, Number(requestedScale) || 1));
    canvas.style.removeProperty("zoom");
    canvas.style.width = `${size.width}px`;
    canvas.style.height = `${size.height}px`;
    canvas.style.transform = `scale(${view.scale})`;
    view.surface.style.width = `${Math.ceil(size.width * view.scale)}px`;
    view.surface.style.height = `${Math.ceil(size.height * view.scale)}px`;
    return view.scale;
  }

  function scale(canvas) {
    return views.get(canvas)?.scale || 1;
  }
  function anchor(node, side, condition = "always") {
    return {
      x: node.x + (side === "output" ? NODE_WIDTH : 0),
      y:
        node.y +
        (side === "output" && node.kind === "gate"
          ? condition === "repair"
            ? 104
            : 66
          : 80),
    };
  }
  function edgePath(source, target, condition, size) {
    const a = anchor(source, "output", condition),
      b = anchor(target, "input");
    if (b.x >= a.x + 25) {
      const bend = Math.max(35, Math.min(120, (b.x - a.x) / 2));
      return `M${a.x},${a.y} C${a.x + bend},${a.y} ${b.x - bend},${b.y} ${b.x},${b.y}`;
    }
    if (target.kind === "validate" && target.y < source.y) {
      const lane = size.width - 16,
        bottom = size.height - 24;
      return `M${a.x},${a.y} L${a.x + 22},${a.y} L${a.x + 22},${bottom} L${lane},${bottom} L${lane},${b.y - 45} L${b.x - 25},${b.y - 45} L${b.x - 25},${b.y} L${b.x},${b.y}`;
    }
    const gap = Math.max(a.y, b.y) + (source.kind === "gate" ? 65 : 50);
    return `M${a.x},${a.y} C${a.x + 40},${a.y} ${a.x + 40},${gap} ${a.x + 10},${gap} L${b.x - 30},${gap} Q${b.x - 48},${gap} ${b.x - 48},${gap - 18} L${b.x - 48},${b.y + 20} Q${b.x - 48},${b.y} ${b.x},${b.y}`;
  }

  const api = { mount, scale, anchor, edgePath, fitScale };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.GraphView = api;
})(typeof window === "undefined" ? globalThis : window);
