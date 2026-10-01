const test = require("node:test");
const assert = require("node:assert/strict");
const M = require("../app/static/nav-menu.js");

test("toggle flips open state", () => {
  assert.equal(M.nextMenuState(false, "toggle"), true);
  assert.equal(M.nextMenuState(true, "toggle"), false);
});

test("choosing an item, Esc, tapping outside and going desktop all close it", () => {
  for (const a of ["select", "escape", "outside", "desktop"]) {
    assert.equal(M.nextMenuState(true, a), false, a);
    assert.equal(M.nextMenuState(false, a), false, a);
  }
});

test("unknown actions keep the current state", () => {
  assert.equal(M.nextMenuState(true, "scroll"), true);
  assert.equal(M.nextMenuState(false, undefined), false);
});

test("burger label follows state", () => {
  assert.equal(M.menuLabel(false), "เปิดเมนู");
  assert.equal(M.menuLabel(true), "ปิดเมนู");
});
