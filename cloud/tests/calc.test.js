const test = require("node:test");
const assert = require("node:assert/strict");
const C = require("../app/static/calc.js");

test("parseAmount accepts plain numbers, commas and decimals", () => {
  assert.equal(C.parseAmount("400"), "400");
  assert.equal(C.parseAmount("1,234.5"), "1234.5");
  assert.equal(C.parseAmount(" 7.25 "), "7.25");
  assert.equal(C.parseAmount("7."), "7");
});

test("parseAmount rejects junk, negatives and too many decimals", () => {
  for (const bad of ["", "abc", "-5", "1.2.3", "7.12345", "1e3", null, undefined]) {
    assert.equal(C.parseAmount(bad), null, String(bad));
  }
});

test("costSatang multiplies exactly", () => {
  assert.equal(C.costSatang("400", "7"), 280000n);
  assert.equal(C.costSatang("86", "7.125"), 61275n);
  assert.equal(C.costSatang("0.1", "0.2"), 2n);      // 0.02 exactly, no float drift
  assert.equal(C.costSatang("1", "0.005"), 1n);      // half-up
  assert.equal(C.costSatang("1", "0.0049"), 0n);
});

test("formatBaht", () => {
  assert.equal(C.formatBaht(280000n), "2,800.00");
  assert.equal(C.formatBaht(61275n), "612.75");
  assert.equal(C.formatBaht(5n), "0.05");
  assert.equal(C.formatBaht(0n), "0.00");
});

test("unitsFromMeter normal and rollover", () => {
  assert.deepEqual(C.unitsFromMeter("3312", "3398"), { units: 86, rollover: false });
  assert.deepEqual(C.unitsFromMeter("9990", "0015"), { units: 25, rollover: true });
  assert.deepEqual(C.unitsFromMeter("0834", "0834"), { units: 0, rollover: false });
  assert.equal(C.unitsFromMeter("", "12"), null);
  assert.equal(C.unitsFromMeter("12a", "13"), null);
});

test("line: units mode", () => {
  const l = C.line({ mode: "units", units: "400", price: "7" });
  assert.equal(l.ok, true);
  assert.equal(l.units, "400");
  assert.equal(l.satang, 280000n);
});

test("line: meter mode with rollover warning", () => {
  const l = C.line({ mode: "meter", prev: "9990", curr: "0015", price: "7" });
  assert.equal(l.units, "25");
  assert.equal(l.rollover, true);
  assert.equal(l.satang, 17500n);
});

test("line: incomplete input is not ok", () => {
  assert.equal(C.line({ mode: "units", units: "", price: "7" }).ok, false);
  assert.equal(C.line({ mode: "meter", prev: "1", curr: "", price: "7" }).ok, false);
});
