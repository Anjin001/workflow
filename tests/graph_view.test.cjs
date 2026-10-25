const { test } = require("node:test");
const assert = require("node:assert/strict");
const view = require("../web/assets/graph-view.js");

function fixture() {
  const viewport = {
    clientWidth: 800,
    replaceChild(surface) {
      this.surface = surface;
    },
  };
  const canvas = {
    parentElement: viewport,
    style: { removeProperty() {} },
    ownerDocument: {
      createElement() {
        return {
          style: {},
          append(child) {
            child.parentElement = this;
          },
        };
      },
    },
  };
  return { canvas, viewport };
}

test("repeated selection redraws preserve scale and card size", () => {
  const { canvas } = fixture();
  const size = { width: 1060, height: 680 };
  const initial = view.mount(canvas, size, "auto");
  for (let i = 0; i < 40; i++) {
    assert.equal(view.mount(canvas, size, "auto"), initial);
    assert.equal(canvas.style.transform, `scale(${initial})`);
  }
  assert.equal(
    canvas.parentElement.style.width,
    `${Math.ceil(1060 * initial)}px`,
  );
});

test("auto-fit measures the unscaled viewport, never the scaled surface", () => {
  const { canvas, viewport } = fixture();
  const size = { width: 1060, height: 680 };
  const initial = view.mount(canvas, size, "auto");
  canvas.parentElement.clientWidth = 400;
  assert.equal(view.mount(canvas, size, "auto", true), initial);
  viewport.clientWidth = 1100;
  assert.equal(view.mount(canvas, size, "auto", true), 1);
});

test("manual zoom survives redraw and content changes until explicit fit", () => {
  const { canvas } = fixture();
  const size = { width: 1060, height: 680 };
  assert.equal(view.mount(canvas, size, "1.25"), 1.25);
  assert.equal(view.mount(canvas, { width: 2000, height: 1000 }, "1.25"), 1.25);
  assert.equal(view.scale(canvas), 1.25);
  assert.equal(
    view.mount(canvas, size, "auto", true),
    view.fitScale(800, 1060),
  );
});

test("edges terminate at the same coordinates as their input and output handles", () => {
  const source = { x: 50, y: 40, kind: "gate" },
    target = { x: 600, y: 300, kind: "custom" };
  for (const condition of ["pass", "repair"]) {
    const a = view.anchor(source, "output", condition),
      b = view.anchor(target, "input");
    const path = view.edgePath(source, target, condition, {
      width: 1060,
      height: 680,
    });
    assert.ok(path.startsWith(`M${a.x},${a.y}`));
    assert.ok(path.endsWith(`${b.x},${b.y}`));
  }
  assert.notEqual(
    view.anchor(source, "output", "pass").y,
    view.anchor(source, "output", "repair").y,
  );
});
