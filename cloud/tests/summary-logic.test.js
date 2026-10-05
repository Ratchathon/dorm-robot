const test = require("node:test");
const assert = require("node:assert/strict");
const S = require("../app/static/summary-logic.js");

const line = (status, extra = {}) => ({ status, ...extra });
const row = (number, water, elec, total = null) => ({ number, water, elec, total });

const ROWS = [
  row("101", line("ok", { id: 1 }), line("ok", { id: 2 }), "593.00"),
  row("102", line("ok", { id: 3 }), line("missing")),
  row("103", line("ok", { id: 5 }), line("review", { id: 6 })),
  row("201", line("ok", { id: 7 }), line("ok", { id: 8 }), "678.00"),
  row("202", line("missing"), line("missing")),
  row("203", line("first", { id: 9 }), line("first", { id: 10 })),
];

test("room status", () => {
  assert.deepEqual(ROWS.map(S.roomStatus), ["complete", "partial", "review", "complete", "missing", "baseline"]);
});

test("filter counts and filtering", () => {
  assert.deepEqual(S.filterCounts(ROWS), { all: 6, review: 1, incomplete: 3, complete: 2 });
  assert.deepEqual(S.filterRooms(ROWS, "review").map((r) => r.number), ["103"]);
  assert.deepEqual(S.filterRooms(ROWS, "incomplete").map((r) => r.number), ["102", "202", "203"]);
  assert.deepEqual(S.filterRooms(ROWS, "complete").map((r) => r.number), ["101", "201"]);
  assert.equal(S.filterRooms(ROWS, "all").length, 6);
  assert.equal(S.filterRooms(ROWS, "nonsense").length, 6);
});

test("average per complete room, rounded to baht", () => {
  assert.equal(S.averagePerRoom(ROWS), "636");
  assert.equal(S.averagePerRoom([row("1", line("missing"), line("missing"))]), null);
});

test("compare electricity with the previous month", () => {
  const periods = [
    { period: "2026-09", elec: { status: "ok", units: 86 } },
    { period: "2026-08", elec: { status: "ok", units: 88 } },
  ];
  assert.equal(S.compareMonth(periods, "2026-09", "elec"), "ไฟใช้น้อยลง 2 หน่วยจากเดือนก่อน");
  periods[1].elec.units = 80;
  assert.equal(S.compareMonth(periods, "2026-09", "elec"), "ไฟใช้มากขึ้น 6 หน่วยจากเดือนก่อน");
  periods[1].elec.units = 86;
  assert.equal(S.compareMonth(periods, "2026-09", "elec"), "ไฟใช้เท่ากับเดือนก่อน");
  periods[1].elec.status = "review";
  assert.equal(S.compareMonth(periods, "2026-09", "elec"), null);
  assert.equal(S.compareMonth(periods.slice(0, 1), "2026-09", "elec"), null);
});

test("room number check mirrors the server rule", () => {
  assert.equal(S.cleanRoomNumber("  101A "), "101A");
  assert.equal(S.cleanRoomNumber("ก-12/3"), "ก-12/3");
  for (const bad of ["", "   ", "<b>", "1".repeat(11), "10 1"]) assert.equal(S.cleanRoomNumber(bad), null, bad);
});

test("delete unlocks only when the exact room number is typed", () => {
  assert.equal(S.deleteUnlocked("101", "101"), true);
  assert.equal(S.deleteUnlocked(" 101 ", "101"), true);
  assert.equal(S.deleteUnlocked("10", "101"), false);
  assert.equal(S.deleteUnlocked("", "101"), false);
  assert.equal(S.deleteUnlocked("101a", "101A"), false);
});
