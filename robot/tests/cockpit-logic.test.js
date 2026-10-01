const test = require("node:test");
const assert = require("node:assert/strict");
const L = require("../static/cockpit-logic.js");

const mv = (o = {}) => ({ forward: false, backward: false, left: false, right: false, ...o });

test("motion label covers every direction", () => {
  assert.equal(L.motionLabel(mv()).text, "หยุดนิ่ง");
  assert.equal(L.motionLabel(mv({ forward: true })).text, "เดินหน้า");
  assert.equal(L.motionLabel(mv({ backward: true })).text, "ถอยหลัง");
  assert.equal(L.motionLabel(mv({ left: true })).text, "หมุนซ้าย");
  assert.equal(L.motionLabel(mv({ right: true })).text, "หมุนขวา");
  assert.equal(L.motionLabel(mv({ forward: true, left: true })).text, "เดินหน้าเลี้ยวซ้าย");
  assert.equal(L.motionLabel(mv({ backward: true, right: true })).text, "ถอยหลังเลี้ยวขวา");
  assert.equal(L.motionLabel(mv({ forward: true })).arrow, "↑");
  assert.equal(L.motionLabel(null).text, "หยุดนิ่ง");
});

test("tilt label follows change direction", () => {
  assert.equal(L.tiltLabel(90, 95), "กล้องเงย");
  assert.equal(L.tiltLabel(90, 85), "กล้องก้ม");
  assert.equal(L.tiltLabel(90, 90), "");
  assert.equal(L.tiltLabel(null, 90), "");
});

test("key mapping", () => {
  assert.equal(L.keyAction("W"), "forward");
  assert.equal(L.keyAction("ArrowUp"), "tiltUp");
  assert.equal(L.keyAction("1"), "presetFloor");
  assert.equal(L.keyAction("2"), "presetWall");
  assert.equal(L.keyAction(" "), "capture");
  assert.equal(L.keyAction("Escape"), "estop");
  assert.equal(L.keyAction("e"), "blower");
  assert.equal(L.keyAction("x"), null);
});

test("reading feedback: incomplete value", () => {
  const f = L.readingFeedback("33", "3312");
  assert.equal(f.canSave, false);
  assert.match(f.text, /4 หลัก/);
});

test("reading feedback: normal usage", () => {
  const f = L.readingFeedback("3398", "3312");
  assert.deepEqual([f.canSave, f.level, f.units], [true, "ok", 86]);
  assert.match(f.text, /86 หน่วย/);
});

test("reading feedback: lower than previous suggests rollover", () => {
  const f = L.readingFeedback("0015", "9990");
  assert.equal(f.level, "warn");
  assert.equal(f.lower, true);
  assert.equal(f.rolloverUnits, 25);
  assert.equal(f.canSave, true);
});

test("reading feedback: unusually high", () => {
  const f = L.readingFeedback("3900", "3312", { highUsage: 300 });
  assert.equal(f.level, "warn");
  assert.match(f.text, /มากผิดปกติ/);
});

test("reading feedback: first ever reading has no previous", () => {
  assert.equal(L.readingFeedback("", null).canSave, false);
  const f = L.readingFeedback("0851", null);
  assert.equal(f.canSave, true);
  assert.match(f.text, /ค่าแรก/);
});

test("reading feedback: non-digits never saveable", () => {
  assert.equal(L.readingFeedback("33a8", "3312").canSave, false);
});

test("sanitizeDigits strips and limits", () => {
  assert.equal(L.sanitizeDigits("3a3-9 8", 4), "3398");
  assert.equal(L.sanitizeDigits("123456", 4), "1234");
});

// ---------- v3 UI ----------
test("modal keys: 1/2 pick meter type only on the type step", () => {
  assert.equal(L.modalKeyAction("type", "1"), "pickWater");
  assert.equal(L.modalKeyAction("type", "2"), "pickElec");
  assert.equal(L.modalKeyAction("room", "1"), null);
  assert.equal(L.modalKeyAction("value", "1"), null); // digits are typed into the input
  assert.equal(L.modalKeyAction("value", "Enter"), "save");
  assert.equal(L.modalKeyAction("room", "Backspace"), "back");
  assert.equal(L.modalKeyAction("value", "Backspace"), null); // deletes a digit instead
});

test("digit slots show filled, active and empty boxes", () => {
  assert.deepEqual(L.digitSlots("33", 4), [
    { ch: "3", state: "filled" }, { ch: "3", state: "filled" },
    { ch: "", state: "active" }, { ch: "", state: "empty" },
  ]);
  assert.deepEqual(L.digitSlots("3398", 4).map((s) => s.state), ["filled", "filled", "filled", "filled"]);
  assert.equal(L.digitSlots("", 5).length, 5);
});

test("digit slots fall back to 4 boxes without a previous reading", () => {
  assert.equal(L.digitSlots("", 0).length, 4);
  assert.equal(L.digitSlots("123456", 0).length, 6); // grows with what is typed
});

test("connection look per state", () => {
  assert.deepEqual(L.connectionLook("connected", 38), { tone: "ok", text: "เชื่อมต่อแล้ว · 38 ms" });
  assert.deepEqual(L.connectionLook("connected", null), { tone: "ok", text: "เชื่อมต่อแล้ว" });
  assert.equal(L.connectionLook("connecting").tone, "pending");
  assert.equal(L.connectionLook("disconnected").tone, "bad");
  assert.equal(L.connectionLook("busy").tone, "bad");
  assert.match(L.connectionLook("busy").text, /ผู้ควบคุม/);
});
