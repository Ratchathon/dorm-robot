(function () {
  "use strict";
  const { el, api, periodLabel, dateTime, baht, currentPeriod, toast, TYPE } = window.UI;
  const S = window.SummaryLogic;
  const $ = (id) => document.getElementById(id);

  const STATUS_PILL = {
    complete: ["ครบ", "ok"], review: ["ต้องตรวจสอบ", "bad"], missing: ["ยังไม่จด", ""],
    partial: ["ขาด 1 มิเตอร์", ""], baseline: ["ค่าฐาน", ""],
  };
  const FILTER_LABEL = { all: "ทั้งหมด", review: "ต้องตรวจสอบ", incomplete: "ยังไม่ครบ", complete: "ครบแล้ว" };
  let periods = [];
  let summary = null;
  let rooms = [];
  let selected = null; // { room, kind }
  let filter = "all";

  // Two-step confirm without blocking browser dialogs.
  function confirmButton(label, confirmLabel, cls, action) {
    const b = el("button", { class: "btn " + cls, type: "button", text: label });
    let armed = false;
    b.addEventListener("click", async () => {
      if (!armed) { armed = true; b.textContent = confirmLabel; setTimeout(() => { armed = false; b.textContent = label; }, 4000); return; }
      b.disabled = true;
      try { await action(); } catch (err) { toast(err.message); } finally { b.disabled = false; armed = false; b.textContent = label; }
    });
    return b;
  }

  // ---------------- navigation ----------------
  function show(view) {
    document.querySelectorAll("[data-view]").forEach((t) => {
      if (t.dataset.view === view) t.setAttribute("aria-current", "page"); else t.removeAttribute("aria-current");
    });
    ["readings", "rooms", "rates", "disputes"].forEach((v) => { $("view-" + v).hidden = v !== view; });
    if (view === "rooms") loadRooms();
    if (view === "rates") loadRates();
    if (view === "disputes") loadDisputes();
    if (view === "readings") loadSummary();
  }
  document.querySelectorAll("[data-view]").forEach((t) => t.addEventListener("click", () => show(t.dataset.view)));
  $("logout").addEventListener("click", async () => { await api("/api/admin/logout", { method: "POST" }); location.href = "/admin/login"; });

  // ---------------- readings ----------------
  async function loadPeriods() {
    const res = await api("/api/admin/periods");
    periods = Array.from(new Set([currentPeriod(), ...res.periods])).sort().reverse();
  }
  function stepPeriod(delta) {
    const i = periods.indexOf(summary.period) + delta; // list is newest first
    if (i < 0 || i >= periods.length) return;
    selected = null;
    loadSummary(periods[i]);
  }
  $("prevPeriod").addEventListener("click", () => stepPeriod(1));
  $("nextPeriod").addEventListener("click", () => stepPeriod(-1));

  async function loadSummary(period) {
    if (!periods.length) await loadPeriods();
    const p = period || (summary && summary.period) || periods.find((x) => x <= currentPeriod()) || currentPeriod();
    summary = await api("/api/admin/summary?period=" + p);
    if (!rooms.length) rooms = (await api("/api/admin/rooms")).rooms;
    render();
  }

  function render() {
    const s = summary;
    $("periodTitle").textContent = periodLabel(s.period);
    const i = periods.indexOf(s.period);
    $("prevPeriod").disabled = i >= periods.length - 1;
    $("nextPeriod").disabled = i <= 0;
    $("rateLine").textContent = s.rates.elec || s.rates.water
      ? "ไฟ " + (s.rates.elec || "—") + " · น้ำ " + (s.rates.water || "—") + " บาท/หน่วย" : "ยังไม่ได้ตั้งราคาต่อหน่วย";

    const avg = S.averagePerRoom(s.rooms);
    const complete = S.filterCounts(s.rooms).complete;
    $("tTotal").textContent = baht(s.grand_total);
    $("tAvg").textContent = avg ? "เฉลี่ยต่อห้อง ฿" + avg + " · " + complete + " ห้องที่ครบ" : "ยังไม่มีห้องที่ครบ";
    const n = s.counts.rooms || 1;
    $("tWater").replaceChildren(String(s.counts.water), el("small", { text: "/" + s.counts.rooms }));
    $("tElec").replaceChildren(String(s.counts.elec), el("small", { text: "/" + s.counts.rooms }));
    $("barWater").style.width = Math.round((s.counts.water / n) * 100) + "%";
    $("barElec").style.width = Math.round((s.counts.elec / n) * 100) + "%";
    $("tReview").textContent = String(s.counts.review);

    const counts = S.filterCounts(s.rooms);
    $("filters").replaceChildren(...Object.keys(FILTER_LABEL).map((k) => el("button", {
      class: "chip-btn", type: "button", "aria-pressed": String(filter === k),
      text: FILTER_LABEL[k] + " " + counts[k], onclick: () => { filter = k; render(); },
    })));

    const shown = S.filterRooms(s.rooms, filter);
    $("roomCards").replaceChildren(...shown.map(roomCard));
    if (!s.rooms.length) $("roomCards").append(el("div", { class: "card pad muted", text: "ยังไม่มีห้อง เพิ่มได้ที่เมนู ห้องและ QR" }));
    else if (!shown.length) $("roomCards").append(el("div", { class: "card pad muted", text: "ไม่มีห้องในกลุ่มนี้" }));
    renderPanel();
  }

  function roomCard(row) {
    const status = S.roomStatus(row);
    const [label, cls] = STATUS_PILL[status];
    return el("article", { class: "card room-card" + (status === "review" ? " flag" : "") },
      el("div", { class: "row" }, el("span", { class: "num grow", text: row.number }), el("span", { class: "pill " + cls, text: label })),
      meterButton(row, "water"), meterButton(row, "elec"),
      el("div", { class: "card-foot" }, el("span", { class: "muted", text: "รวม" }), el("b", { text: row.total ? baht(row.total) : "—" })));
  }

  function meterButton(row, kind) {
    const line = row[kind];
    const current = selected && selected.room === row.number && selected.kind === kind;
    const btn = el("button", { class: "meter-btn", type: "button", "aria-current": current ? "true" : null,
      "aria-label": "ห้อง " + row.number + " มิเตอร์" + TYPE[kind],
      onclick: () => { selected = { room: row.number, kind }; render(); } },
      el("span", { class: "tag", text: TYPE[kind] }));
    if (!line.id) { btn.append(el("span", { class: "missing", text: "ยังไม่ได้จด · กดเพื่อกรอกเอง" })); return btn; }
    if (line.has_image) btn.append(el("img", { class: "thumb", alt: "", loading: "lazy", src: "/api/admin/readings/" + line.id + "/image" }));
    const sub = line.status === "review" ? "น้อยกว่า " + line.prev_value
      : line.units !== null && line.units !== undefined ? "จาก " + line.prev_value + " · " + line.units + " หน่วย"
      : line.status === "first" ? "ค่าแรก (ฐาน)" : "";
    btn.append(el("span", { class: "grow" }, el("div", { class: "mv", text: line.value + (line.edited ? " ✎" : "") }),
      el("div", { class: "ms" + (line.status === "review" ? " bad" : ""), text: sub })),
      el("span", { class: "amt", text: line.amount ? baht(line.amount) : "—" }));
    return btn;
  }

  function renderPanel() {
    const panel = $("panel");
    if (!selected) return;
    const row = summary.rooms.find((r) => r.number === selected.room);
    if (!row) { selected = null; return; }
    const kind = selected.kind;
    const line = row[kind];
    panel.replaceChildren(el("div", { class: "row" },
      el("div", { class: "grow" }, el("div", { class: "muted small", text: "ห้อง " + row.number }), el("h2", { text: "มิเตอร์" + TYPE[kind] })),
      line.status === "review" ? el("span", { class: "pill bad", text: "ต้องตรวจสอบ" }) : null));

    if (!line.id) { panel.append(manualForm(row.number, kind)); return; }

    panel.append(line.has_image
      ? el("a", { href: "/api/admin/readings/" + line.id + "/image", target: "_blank", rel: "noopener" },
          el("img", { class: "photo", alt: "ภาพมิเตอร์" + TYPE[kind] + " ห้อง " + row.number, src: "/api/admin/readings/" + line.id + "/image" }))
      : el("div", { class: "photo empty", text: "ผู้ดูแลบันทึกเอง ไม่มีภาพ" }));
    panel.append(el("div", { class: "kv" },
      el("div", null, el("div", { class: "k", text: "เลขที่จด" }), el("div", { class: "v", text: line.value })),
      el("div", null, el("div", { class: "k", text: "ครั้งก่อน" }), el("div", { class: "v", text: line.prev_value || "—" }))));
    if (line.status === "review") {
      const diff = parseInt(line.prev_value, 10) - parseInt(line.value, 10);
      panel.append(el("div", { class: "note bad", text: "น้อยกว่าครั้งก่อน " + diff + " หน่วย ดูภาพแล้วแก้เลข หรือยืนยันว่ามิเตอร์วนรอบ" }));
    } else if (line.status === "ok") {
      panel.append(el("div", { class: "note ok", text: line.units + " หน่วย × " + line.price + " บาท = " + baht(line.amount) + (line.rollover ? " (มิเตอร์วนรอบ)" : "") }));
    } else if (line.status === "first") {
      panel.append(el("div", { class: "note plain", text: "ค่าแรกของมิเตอร์นี้ ใช้เป็นฐานของเดือนถัดไป" }));
    }

    const value = el("input", { class: "input big", id: "fixValue", inputmode: "numeric", value: line.value, maxlength: "8" });
    const note = el("input", { class: "input", id: "fixNote", placeholder: "เหตุผล (ไม่บังคับ)", maxlength: "300", "aria-label": "เหตุผลที่แก้" });
    const form = el("form", { class: "stack" },
      el("div", { class: "field" }, el("label", { for: "fixValue", text: "แก้เลข" }),
        el("div", { class: "row" }, el("div", { class: "grow" }, value), el("button", { class: "btn primary", type: "submit", text: "บันทึก" }))),
      note);
    form.addEventListener("submit", (e) => { e.preventDefault(); patch(line.id, { value: value.value.trim(), note: note.value }, "แก้เลขแล้ว"); });
    panel.append(form);

    const move = el("select", { class: "input", "aria-label": "ย้ายไปห้อง" },
      ...rooms.filter((r) => r.number !== row.number).map((r) => el("option", { value: r.number, text: "ห้อง " + r.number })));
    const actions = el("div", { class: "row" });
    if (line.status === "review") {
      actions.append(confirmButton("มิเตอร์วนรอบ", "กดอีกครั้งเพื่อยืนยัน", "soft small", () => patch(line.id, { rollover: true }, "ยืนยันมิเตอร์วนรอบแล้ว")));
    }
    actions.append(confirmButton("ลบ", "กดอีกครั้งเพื่อลบ", "danger small", async () => {
      await api("/api/admin/readings/" + line.id, { method: "DELETE" });
      toast("ลบแล้ว (ยังดูได้ในประวัติ)");
      loadSummary();
    }));
    panel.append(actions, el("div", { class: "row" }, el("div", { class: "grow" }, move),
      el("button", { class: "btn small", type: "button", text: "ย้ายห้อง", onclick: () => patch(line.id, { room: move.value }, "ย้ายไปห้อง " + move.value + " แล้ว") })));
    panel.append(el("div", { class: "muted small", text: (line.source === "robot" ? "ถ่ายโดยหุ่น " : "ผู้ดูแลบันทึก ") + dateTime(line.captured_at) + " · การแก้ไขทุกครั้งเก็บประวัติไว้" }));
    api("/api/admin/readings/" + line.id + "/history").then(({ history }) => {
      if (!history.length) return;
      panel.append(el("h2", { text: "ประวัติการแก้ไข" }), el("ul", { class: "hist" }, ...history.map((h) =>
        el("li", { text: dateTime(h.at) + " · " + describe(h) + (h.note ? " · " + h.note : "") }))));
    });
  }

  function describe(h) {
    if (h.action === "delete") return "ลบค่า " + h.old_value;
    const parts = [];
    if (h.new_value) parts.push(h.old_value + " → " + h.new_value);
    if (h.new_room) parts.push("ย้ายห้อง " + h.old_room + " → " + h.new_room);
    if (h.new_rollover !== null && h.new_rollover !== undefined) parts.push(h.new_rollover ? "ยืนยันมิเตอร์วนรอบ" : "ยกเลิกวนรอบ");
    return parts.join(", ") || "แก้ไข";
  }

  function manualForm(room, kind) {
    const value = el("input", { class: "input big", id: "manualValue", inputmode: "numeric", maxlength: "8", required: true });
    const form = el("form", { class: "stack" },
      el("div", { class: "note plain", text: "ยังไม่มีค่าของเดือนนี้ ถ้าหุ่นจดไม่ได้ ผู้ดูแลกรอกเลขเองได้" }),
      el("div", { class: "field" }, el("label", { for: "manualValue", text: "เลขบนมิเตอร์" }), value),
      el("button", { class: "btn primary", type: "submit", text: "บันทึกค่า" }));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const [y, m] = summary.period.split("-").map(Number);
        const inPeriod = summary.period === currentPeriod() ? undefined : new Date(Date.UTC(y, m, 0, 5)).toISOString();
        await api("/api/admin/readings", { json: { room, meter_type: kind, value: value.value.trim(), captured_at: inPeriod } });
        toast("บันทึกแล้ว");
        loadSummary();
      } catch (err) { toast(err.message); }
    });
    return form;
  }

  async function patch(id, body, okMsg) {
    try {
      await api("/api/admin/readings/" + id, { method: "PATCH", json: body });
      toast(okMsg);
      if (body.room) selected = { room: body.room, kind: selected.kind };
      await loadSummary();
    } catch (err) { toast(err.message); }
  }

  $("exportCsv").addEventListener("click", () => {
    const head = ["ห้อง", "น้ำ-ครั้งก่อน", "น้ำ-เดือนนี้", "น้ำ-หน่วย", "น้ำ-บาท", "ไฟ-ครั้งก่อน", "ไฟ-เดือนนี้", "ไฟ-หน่วย", "ไฟ-บาท", "รวม"];
    const lines = summary.rooms.map((r) => [r.number, r.water.prev_value, r.water.value, r.water.units, r.water.amount,
      r.elec.prev_value, r.elec.value, r.elec.units, r.elec.amount, r.total]);
    const csv = [head, ...lines].map((cols) => cols.map((c) => {
      const v = c === null || c === undefined ? "" : String(c);
      return /^[=+\-@]/.test(v) ? "'" + v : '"' + v.replace(/"/g, '""') + '"';
    }).join(",")).join("\r\n");
    const a = el("a", { href: URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv" })), download: "meters-" + summary.period + ".csv" });
    document.body.append(a); a.click(); a.remove();
  });
  $("print").addEventListener("click", () => window.print());

  // ---------------- rooms ----------------
  async function loadRooms(selectId) {
    rooms = (await api("/api/admin/rooms")).rooms;
    const list = $("roomList");
    list.replaceChildren(...rooms.map((r) => el("div", { class: "list-row" },
      el("div", { class: "num", text: r.number }),
      el("div", { class: "stack" }, el("div", { class: "link-box", text: r.link }),
        el("span", { class: "pill " + (r.active ? "ok" : ""), text: r.active ? "ใช้งาน" : "ปิดใช้งาน" })),
      el("div", { class: "row actions" },
        el("button", { class: "btn small", type: "button", text: "คัดลอกลิงก์", onclick: () => copy(r.link) }),
        el("button", { class: "btn small", type: "button", text: "QR / จัดการ", onclick: () => roomPanel(r) })))));
    if (!rooms.length) list.append(el("div", { class: "list-row muted", text: "ยังไม่มีห้อง" }));
    const sel = rooms.find((r) => r.id === selectId);
    if (sel) roomPanel(sel);
  }

  async function copy(text) {
    try { await navigator.clipboard.writeText(text); toast("คัดลอกลิงก์แล้ว"); } catch (e) { toast(text); }
  }

  function roomPanel(r) {
    $("roomPanel").replaceChildren(
      el("h2", { text: "ห้อง " + r.number }),
      el("img", { class: "qr", alt: "QR ลิงก์ห้อง " + r.number, src: "/api/admin/rooms/" + r.id + "/qr.svg?v=" + encodeURIComponent(r.token.slice(0, 6)) }),
      el("div", { class: "muted small", text: "พิมพ์ QR ติดในห้อง หรือส่งลิงก์ทาง LINE ให้ลูกบ้าน" }),
      el("a", { class: "btn", href: r.link, target: "_blank", rel: "noopener", text: "เปิดหน้าลูกบ้าน" }),
      confirmButton("ลิงก์หลุด: สร้างลิงก์ใหม่", "ลิงก์เดิมจะใช้ไม่ได้ · กดยืนยัน", "", () => newLink(r, false)),
      confirmButton("ผู้เช่าใหม่ย้ายเข้า", "ซ่อนภาพเก่าจากลิงก์ใหม่ · กดยืนยัน", "", () => newLink(r, true)),
      el("div", { class: "muted small", text: "ผู้เช่าใหม่: ลิงก์เดิมใช้ไม่ได้ และลิงก์ใหม่จะไม่เห็นภาพและยอดของผู้เช่าคนก่อน" }),
      el("button", { class: "btn " + (r.active ? "danger" : ""), type: "button", text: r.active ? "ปิดใช้งานห้องนี้" : "เปิดใช้งานห้องนี้",
        onclick: async () => { await api("/api/admin/rooms/" + r.id, { method: "PATCH", json: { active: !r.active } }); loadRooms(r.id); } }));
  }

  async function newLink(r, newTenant) {
    await api("/api/admin/rooms/" + r.id + "/new-link", { json: { new_tenant: newTenant } });
    toast(newTenant ? "สร้างลิงก์สำหรับผู้เช่าใหม่แล้ว" : "สร้างลิงก์ใหม่แล้ว");
    loadRooms(r.id);
  }

  $("addRoom").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const r = await api("/api/admin/rooms", { json: { number: $("newRoom").value.trim() } });
      $("newRoom").value = "";
      toast("เพิ่มห้อง " + r.number + " แล้ว");
      loadRooms(r.id);
    } catch (err) { toast(err.message); }
  });

  // ---------------- rates ----------------
  async function loadRates() {
    const r = await api("/api/admin/rates");
    if (r.current) { $("rateElec").value = r.current.elec || ""; $("rateWater").value = r.current.water || ""; }
    $("rateHistory").replaceChildren(...r.history.map((h) => el("li", { text: dateTime(h.effective_from) + " · " + TYPE[h.meter_type] + " " + h.price + " บาท/หน่วย" })));
    if (!r.history.length) $("rateHistory").append(el("li", { text: "ยังไม่ได้ตั้งราคา" }));
  }
  $("rateForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/admin/rates", { method: "PUT", json: { elec: $("rateElec").value.trim(), water: $("rateWater").value.trim() } });
      toast("บันทึกราคาแล้ว");
      loadRates();
    } catch (err) { toast(err.message); }
  });

  // ---------------- disputes ----------------
  async function loadDisputes() {
    const { disputes } = await api("/api/admin/disputes");
    const open = disputes.filter((d) => d.status === "open").length;
    $("disputeCount").textContent = String(open);
    $("disputeCount").hidden = !open;
    const list = $("disputeList");
    list.replaceChildren(...disputes.map((d) => {
      const reply = el("textarea", { class: "input", "aria-label": "ตอบกลับห้อง " + d.room, maxlength: "1000" });
      reply.value = d.reply || "";
      return el("article", { class: "card pad stack" },
        el("div", { class: "row" }, el("b", { text: "ห้อง " + d.room }),
          el("span", { class: "muted small grow", text: "รอบ " + periodLabel(d.period) + " · " + dateTime(d.created_at) }),
          el("span", { class: "pill " + (d.status === "open" ? "bad" : "ok"), text: d.status === "open" ? "รอตอบ" : "ตอบแล้ว" })),
        el("div", { text: d.message }), reply,
        el("div", { class: "row" }, el("button", { class: "btn primary", type: "button", text: "ตอบและปิดเรื่อง",
          onclick: async () => { await api("/api/admin/disputes/" + d.id, { method: "PATCH", json: { reply: reply.value, status: "resolved" } }); toast("ตอบแล้ว"); loadDisputes(); } })));
    }));
    if (!disputes.length) list.append(el("div", { class: "card pad muted", text: "ยังไม่มีเรื่องแจ้ง" }));
  }

  // ---------------- start ----------------
  api("/api/admin/me").then((me) => {
    $("dormName").textContent = me.dorm_name;
    $("logo").textContent = (me.dorm_name || "ห").trim().charAt(0);
    loadSummary();
    loadDisputes();
  }).catch((err) => {
    if (err.status === 401) location.href = "/admin/login";
    else toast(err.message);
  });
})();
