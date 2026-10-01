// Pure helpers for the cockpit page. No DOM here, so they run under `node --test`.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.CockpitLogic = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function motionLabel(move) {
    const m = move || {};
    const f = m.forward === true, b = m.backward === true, l = m.left === true, r = m.right === true;
    if (f && l) return { arrow: "↖", text: "เดินหน้าเลี้ยวซ้าย" };
    if (f && r) return { arrow: "↗", text: "เดินหน้าเลี้ยวขวา" };
    if (b && l) return { arrow: "↙", text: "ถอยหลังเลี้ยวซ้าย" };
    if (b && r) return { arrow: "↘", text: "ถอยหลังเลี้ยวขวา" };
    if (f) return { arrow: "↑", text: "เดินหน้า" };
    if (b) return { arrow: "↓", text: "ถอยหลัง" };
    if (l) return { arrow: "↺", text: "หมุนซ้าย" };
    if (r) return { arrow: "↻", text: "หมุนขวา" };
    return { arrow: "·", text: "หยุดนิ่ง" };
  }

  function tiltLabel(prevTilt, tilt) {
    if (typeof prevTilt !== "number" || typeof tilt !== "number" || prevTilt === tilt) return "";
    return tilt > prevTilt ? "กล้องเงย" : "กล้องก้ม";
  }

  const KEYS = {
    w: "forward", s: "backward", a: "left", d: "right",
    arrowup: "tiltUp", arrowdown: "tiltDown",
    "1": "presetFloor", "2": "presetWall",
    e: "blower", " ": "capture", escape: "estop",
  };

  function keyAction(key) {
    return KEYS[String(key || "").toLowerCase()] || null;
  }

  function sanitizeDigits(text, maxLen) {
    return String(text || "").replace(/\D/g, "").slice(0, maxLen || 8);
  }

  // Validate what the operator typed against the previous reading.
  function readingFeedback(value, prev, opts) {
    const highUsage = (opts && opts.highUsage) || 500;
    const v = String(value || "");
    if (!/^\d*$/.test(v)) return { canSave: false, level: "muted", text: "ใส่ได้เฉพาะตัวเลข" };
    if (!prev) {
      if (!v) return { canSave: false, level: "muted", text: "พิมพ์เลขตามภาพ" };
      return { canSave: true, level: "muted", text: "ค่าแรกของมิเตอร์นี้ ยังไม่มีค่าครั้งก่อนให้เทียบ" };
    }
    const digits = prev.length;
    if (v.length !== digits) return { canSave: false, level: "muted", text: "ใส่ให้ครบ " + digits + " หลัก" };
    const units = parseInt(v, 10) - parseInt(prev, 10);
    if (units < 0) {
      const rolloverUnits = units + Math.pow(10, digits);
      return {
        canSave: true, level: "warn", lower: true, rolloverUnits,
        text: "น้อยกว่าครั้งก่อน ตรวจเลขอีกครั้ง หรือติ๊ก \"มิเตอร์วนรอบ\" (= " + rolloverUnits + " หน่วย)",
      };
    }
    if (units > highUsage) return { canSave: true, level: "warn", units, text: "ใช้ไป " + units + " หน่วย · มากผิดปกติ ตรวจเลขอีกครั้ง" };
    return { canSave: true, level: "ok", units, text: "ใช้ไป " + units + " หน่วย" };
  }

  // Keys inside the capture dialog. Digits on the value step go to the input itself.
  function modalKeyAction(step, key) {
    if (step === "type" && key === "1") return "pickWater";
    if (step === "type" && key === "2") return "pickElec";
    if (step === "value" && key === "Enter") return "save";
    if (step !== "value" && key === "Backspace") return "back";
    return null;
  }

  // One box per digit (OTP style). Without a previous reading: at least 4 boxes, growing as typed.
  function digitSlots(value, len) {
    const v = String(value || "");
    const n = len > 0 ? len : Math.max(4, v.length);
    const out = [];
    for (let i = 0; i < n; i++) {
      out.push({ ch: v[i] || "", state: i < v.length ? "filled" : i === v.length ? "active" : "empty" });
    }
    return out;
  }

  function connectionLook(state, latencyMs) {
    if (state === "connected") return { tone: "ok", text: "เชื่อมต่อแล้ว" + (latencyMs != null ? " · " + latencyMs + " ms" : "") };
    if (state === "busy") return { tone: "bad", text: "มีผู้ควบคุมอยู่แล้ว" };
    if (state === "disconnected") return { tone: "bad", text: "ขาดการเชื่อมต่อ" };
    return { tone: "pending", text: "กำลังเชื่อมต่อ…" };
  }

  return { motionLabel, tiltLabel, keyAction, sanitizeDigits, readingFeedback, modalKeyAction, digitSlots, connectionLook };
});
