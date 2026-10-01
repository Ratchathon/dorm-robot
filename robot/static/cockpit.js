// Cockpit page: drives the robot over WebSocket and records meter readings.
(function () {
  "use strict";
  const L = window.CockpitLogic;
  const $ = (id) => document.getElementById(id);

  const SEND_INTERVAL_MS = 100;
  const TILT_STEP = 3;
  let cfg = { ws_port: 8765, tilt_floor: 35, tilt_wall: 110, cloud_url: "" };

  // ---------- state ----------
  const pressed = new Set();
  let tilt = 90;
  let blower = false;
  let socket = null;
  let connected = false;
  let lastAckTilt = null;
  let lastSendAt = 0;
  let modalOpen = false;

  // ---------- helpers ----------
  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => t.classList.remove("show"), 2500);
  }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  async function api(path, opts) {
    const res = await fetch(path, opts);
    let body = {};
    try { body = await res.json(); } catch (e) { /* image or empty */ }
    if (!res.ok) throw new Error(body.error || "HTTP " + res.status);
    return body;
  }
  function span(cls, text) {
    const s = document.createElement("span");
    if (cls) s.className = cls;
    s.textContent = text;
    return s;
  }

  // ---------- connection + motion status ----------
  function setConn(state, latency) {
    const look = L.connectionLook(state, latency);
    $("connPill").className = "pill " + look.tone;
    $("connText").textContent = look.text;
  }

  function showMotion(cmd) {
    const m = L.motionLabel(cmd && cmd.move);
    $("motionArrow").textContent = m.arrow;
    $("motionText").textContent = m.text;
    const t = cmd ? L.tiltLabel(lastAckTilt, cmd.tilt) : "";
    $("tiltText").textContent = t;
    $("tiltSep").hidden = !t;
    if (cmd) lastAckTilt = cmd.tilt;
  }

  function connect() {
    setConn("connecting");
    socket = new WebSocket("ws://" + location.hostname + ":" + cfg.ws_port);
    socket.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.type === "hello") {
        connected = true;
        tilt = typeof msg.tilt === "number" ? msg.tilt : tilt;
        lastAckTilt = tilt;
        renderHud();
        setConn("connected");
      } else if (msg.type === "busy") {
        setConn("busy");
      } else if (msg.type === "ack") {
        setConn("connected", Math.round(performance.now() - lastSendAt));
        showMotion(msg.cmd);
      }
    };
    socket.onclose = (ev) => {
      connected = false;
      showMotion(null);
      if (ev.code === 4001) { setConn("busy"); setTimeout(connect, 5000); }
      else { setConn("disconnected"); setTimeout(connect, 1000); }
    };
    socket.onerror = () => socket.close();
  }

  function sendState() {
    if (!socket || socket.readyState !== WebSocket.OPEN || !connected) return;
    const drive = !modalOpen;
    if (drive && pressed.has("tiltUp")) tilt = clamp(tilt + TILT_STEP, 0, 180);
    if (drive && pressed.has("tiltDown")) tilt = clamp(tilt - TILT_STEP, 0, 180);
    renderHud();
    lastSendAt = performance.now();
    socket.send(JSON.stringify({
      move: {
        forward: drive && pressed.has("forward"),
        backward: drive && pressed.has("backward"),
        left: drive && pressed.has("left"),
        right: drive && pressed.has("right"),
      },
      tilt: tilt,
      blower: blower,
    }));
  }

  // ---------- controls ----------
  function renderHud() {
    $("tiltVal").textContent = tilt;
    $("blowerVal").textContent = blower ? "ON" : "OFF";
    $("blowerBtn").setAttribute("aria-checked", String(blower));
  }
  function clearEstop() { $("estopBanner").hidden = true; }
  function toggleBlower() { blower = !blower; clearEstop(); renderHud(); sendState(); }
  function estop() {
    pressed.clear();
    blower = false;
    $("estopBanner").hidden = false;
    renderHud();
    sendState();
  }
  function preset(value) { tilt = value; clearEstop(); renderHud(); sendState(); }
  function setZoom(z) {
    $("scene").classList.toggle("z2", z === 2);
    document.querySelectorAll("[data-zoom]").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.zoom) === z)));
  }

  $("blowerBtn").addEventListener("click", toggleBlower);
  $("estopBtn").addEventListener("click", estop);
  $("captureBtn").addEventListener("click", startCapture);
  document.querySelectorAll("[data-zoom]").forEach((b) => b.addEventListener("click", () => setZoom(Number(b.dataset.zoom))));

  window.addEventListener("keydown", (e) => {
    const action = L.keyAction(e.key);
    if (action === "estop") { e.preventDefault(); estop(); if (modalOpen) closeModal(); return; }
    if (modalOpen) { handleModalKey(e); return; } // typing a number must never drive the robot
    if (!action) return;
    e.preventDefault();
    if (e.repeat && ["blower", "capture", "presetFloor", "presetWall"].includes(action)) return;
    clearEstop();
    if (action === "blower") toggleBlower();
    else if (action === "capture") startCapture();
    else if (action === "presetFloor") preset(cfg.tilt_floor);
    else if (action === "presetWall") preset(cfg.tilt_wall);
    else pressed.add(action);
  });
  window.addEventListener("keyup", (e) => { pressed.delete(L.keyAction(e.key)); });
  window.addEventListener("blur", () => pressed.clear());
  document.addEventListener("visibilitychange", () => { if (document.hidden) pressed.clear(); });

  // ---------- capture flow: shoot -> type -> room -> value ----------
  const flow = { step: "type", captureId: null, type: null, room: null, rooms: [], prev: null };
  const TYPE_LABEL = { water: "น้ำ", elec: "ไฟ" };

  function handleModalKey(e) {
    if (e.repeat) return;
    const act = L.modalKeyAction(flow.step, e.key);
    if (!act) return;
    if (act === "back" && e.target.tagName === "INPUT") return;
    e.preventDefault();
    if (act === "pickWater") pickType("water");
    else if (act === "pickElec") pickType("elec");
    else if (act === "back") showStep(flow.step === "value" ? "room" : "type");
    else if (act === "save") $("stepValue").requestSubmit();
  }

  function showStep(step) {
    flow.step = step;
    $("stepType").hidden = step !== "type";
    $("stepRoom").hidden = step !== "room";
    $("stepValue").hidden = step !== "value";
    const n = { type: 1, room: 2, value: 3 }[step];
    $("stepText").textContent = "ขั้น " + n + " จาก 3";
    document.querySelectorAll(".steps i").forEach((bar, i) => bar.classList.toggle("on", i < n));
    const t = TYPE_LABEL[flow.type];
    $("modalTitle").textContent = step === "type" ? "มิเตอร์ชนิดไหน"
      : step === "room" ? "มิเตอร์" + t + " · เลือกห้อง"
      : "ห้อง " + flow.room + " · มิเตอร์" + t;
  }

  async function startCapture() {
    if (modalOpen) return;
    pressed.clear();
    sendState(); // stop the wheels before the dialog takes the keyboard
    try {
      const [cap, rooms] = await Promise.all([api("/api/capture", { method: "POST" }), api("/api/rooms")]);
      flow.captureId = cap.capture_id;
      flow.rooms = rooms.rooms;
      $("shotImg").src = "/api/capture/" + cap.capture_id + ".jpg";
      modalOpen = true;
      $("modal").hidden = false;
      showStep("type");
      document.querySelector(".type-btn").focus();
    } catch (err) {
      toast("ถ่ายภาพไม่สำเร็จ: " + err.message);
    }
  }

  function closeModal() {
    modalOpen = false;
    $("modal").hidden = true;
    flow.captureId = null;
    $("captureBtn").focus();
  }

  function pickType(type) {
    flow.type = type;
    renderRooms();
    showStep("room");
    const first = document.querySelector(".room-btn");
    if (first) first.focus();
  }

  function renderRooms() {
    const grid = $("roomGrid");
    grid.replaceChildren();
    flow.rooms.forEach((r) => {
      const done = r.done && r.done[flow.type];
      const b = document.createElement("button");
      b.type = "button";
      b.className = "room-btn" + (done ? " done" : "");
      b.append(r.number);
      if (done) { const s = document.createElement("small"); s.textContent = "จดแล้ว"; b.append(s); }
      b.addEventListener("click", () => pickRoom(r));
      grid.append(b);
    });
    if (!flow.rooms.length) grid.textContent = "ยังไม่มีรายชื่อห้อง";
  }

  function pickRoom(r) {
    flow.room = r.number;
    const p = r.prev && r.prev[flow.type];
    flow.prev = p ? p.value : null;
    const when = p ? new Date(p.captured_at).toLocaleDateString("th-TH", { day: "numeric", month: "short" }) : "";
    $("prevLabel").textContent = p ? "ครั้งก่อน · " + when : "ยังไม่มีค่าครั้งก่อน";
    $("prevValue").textContent = flow.prev || "—";
    $("valueInput").value = "";
    $("rolloverChk").checked = false;
    $("saveError").hidden = true;
    updateFeedback();
    showStep("value");
    $("valueInput").focus();
  }

  function updateFeedback() {
    const input = $("valueInput");
    const len = flow.prev ? flow.prev.length : 0;
    input.value = L.sanitizeDigits(input.value, len || 8);
    $("digits").replaceChildren(...L.digitSlots(input.value, len).map((s) => span(s.state, s.ch)));
    const f = L.readingFeedback(input.value, flow.prev);
    $("feedback").textContent = f.text;
    $("feedback").className = "feedback " + (f.level === "muted" ? "" : f.level);
    $("rolloverRow").hidden = !f.lower;
    $("saveBtn").disabled = !f.canSave;
  }

  document.querySelectorAll(".type-btn").forEach((b) => b.addEventListener("click", () => pickType(b.dataset.type)));
  document.querySelectorAll("[data-back]").forEach((b) => b.addEventListener("click", () => showStep(b.dataset.back)));
  $("modalClose").addEventListener("click", closeModal);
  $("retakeBtn").addEventListener("click", closeModal);
  $("modal").addEventListener("click", (e) => { if (e.target === $("modal")) closeModal(); });
  $("valueInput").addEventListener("input", updateFeedback);
  $("valueInput").addEventListener("focus", updateFeedback);
  $("valueInput").addEventListener("blur", updateFeedback);

  $("stepValue").addEventListener("submit", async (e) => {
    e.preventDefault();
    if ($("saveBtn").disabled) return;
    $("saveBtn").disabled = true;
    try {
      await api("/api/readings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          capture_id: flow.captureId, room: flow.room, meter_type: flow.type,
          value: $("valueInput").value, client_time: new Date().toISOString(),
          rollover: $("rolloverChk").checked && !$("rolloverRow").hidden,
        }),
      });
      toast("บันทึกห้อง " + flow.room + " · มิเตอร์" + TYPE_LABEL[flow.type] + " แล้ว");
      closeModal();
      refreshStatus();
    } catch (err) {
      $("saveError").textContent = err.message;
      $("saveError").hidden = false;
      $("saveBtn").disabled = false;
    }
  });

  // ---------- upload status ----------
  const STATE_LABEL = { pending: "รอส่ง", sent: "ส่งแล้ว", rejected: "ถูกปฏิเสธ" };
  async function refreshStatus() {
    try {
      const s = await api("/api/status");
      $("pendingCount").textContent = s.pending;
      const list = $("recentList");
      list.replaceChildren(...s.recent.map((r) => {
        const row = document.createElement("div");
        row.className = "rrow";
        const st = span("state " + r.status, STATE_LABEL[r.status] || r.status);
        if (r.error && r.status === "rejected") st.title = r.error;
        const room = document.createElement("b");
        room.textContent = r.room;
        row.append(room, span("muted", "มิเตอร์" + TYPE_LABEL[r.meter_type]), span("val", r.value), st);
        return row;
      }));
      if (!s.recent.length) list.append(span("empty", "ยังไม่มีการบันทึก"));
    } catch (e) { /* robot server restarting; try again next tick */ }
  }

  // ---------- start ----------
  api("/api/config").then((c) => { cfg = Object.assign(cfg, c); }).catch(() => {}).finally(() => {
    if (cfg.cloud_url) { $("cloudLink").href = cfg.cloud_url; $("cloudLink").hidden = false; }
    renderHud();
    connect();
    setInterval(sendState, SEND_INTERVAL_MS);
    refreshStatus();
    setInterval(refreshStatus, 3000);
  });
})();
