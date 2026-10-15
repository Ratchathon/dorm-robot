// Pure helpers for the admin/tenant pages (no DOM, tested with node --test).
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.SummaryLogic = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // complete | review | partial | missing | baseline
  function roomStatus(row) {
    const s = [row.water.status, row.elec.status];
    if (s.includes("review")) return "review";
    if (row.total) return "complete";
    if (s.every((x) => x === "missing")) return "missing";
    if (s.includes("missing")) return "partial";
    return "baseline"; // first readings / no rate: recorded but nothing to bill yet
  }

  const FILTERS = {
    all: () => true,
    review: (st) => st === "review",
    complete: (st) => st === "complete",
    incomplete: (st) => st === "partial" || st === "missing" || st === "baseline",
  };

  function filterRooms(rows, filter) {
    const keep = FILTERS[filter] || FILTERS.all;
    return rows.filter((r) => keep(roomStatus(r)));
  }

  function filterCounts(rows) {
    const out = {};
    for (const k of Object.keys(FILTERS)) out[k] = filterRooms(rows, k).length;
    return out;
  }

  function withCommas(n) {
    return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  // Average bill of rooms that are fully billed, rounded half-up to whole baht (satang math).
  function averagePerRoom(rows) {
    const totals = rows.filter((r) => r.total).map((r) => Math.round(parseFloat(r.total) * 100));
    if (!totals.length) return null;
    const sum = totals.reduce((a, b) => a + b, 0);
    return withCommas(Math.floor((sum / totals.length + 50) / 100));
  }

  const TYPE = { water: "น้ำ", elec: "ไฟ" };
  function compareMonth(periods, period, kind) {
    const i = periods.findIndex((p) => p.period === period);
    const now = periods[i], before = periods[i + 1];
    if (!now || !before || now[kind].status !== "ok" || before[kind].status !== "ok") return null;
    const diff = now[kind].units - before[kind].units;
    if (diff === 0) return TYPE[kind] + "ใช้เท่ากับเดือนก่อน";
    return TYPE[kind] + "ใช้" + (diff < 0 ? "น้อยลง " : "มากขึ้น ") + Math.abs(diff) + " หน่วยจากเดือนก่อน";
  }

  // Bars for the tenant history chart: last 6 months, oldest first. Units come from the meter
  // readings alone, so they show even before the admin has set a price ("no_rate").
  function historyBars(periods, kind) {
    return (periods || []).slice(0, 6).reverse().map((p) => {
      const l = p[kind];
      return { period: p.period, units: l && (l.status === "ok" || l.status === "no_rate") ? l.units : null };
    });
  }

  // same rule as ROOM_RE on the server; returns the trimmed number or null
  const ROOM_RE = /^[0-9A-Za-z\u0E00-\u0E7F/-]{1,10}$/;
  function cleanRoomNumber(value) {
    const v = String(value == null ? "" : value).trim();
    return ROOM_RE.test(v) ? v : null;
  }

  function deleteUnlocked(typed, number) {
    return String(typed == null ? "" : typed).trim() === number;
  }

  function photoCount(rows) {
    return (rows || []).reduce((n, r) => n + ["water", "elec"].filter((t) => r[t] && r[t].has_image).length, 0);
  }

  return { roomStatus, filterRooms, filterCounts, averagePerRoom, compareMonth, historyBars, cleanRoomNumber, deleteUnlocked, photoCount };
});
