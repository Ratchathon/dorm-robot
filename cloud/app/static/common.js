// Small DOM + API helpers shared by all pages. Text is always set with textContent (no innerHTML).
(function () {
  "use strict";

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      node.append(c instanceof Node ? c : String(c));
    }
    return node;
  }

  async function api(path, opts = {}) {
    const init = { credentials: "same-origin", ...opts };
    if (opts.json !== undefined) {
      init.method = init.method || "POST";
      init.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
      init.body = JSON.stringify(opts.json);
      delete init.json;
    }
    const res = await fetch(path, init);
    let body = null;
    try { body = await res.json(); } catch (e) { /* empty */ }
    if (!res.ok) {
      const err = new Error((body && body.detail) || "HTTP " + res.status);
      err.status = res.status;
      throw err;
    }
    return body;
  }

  const MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."];
  function periodLabel(p, short) {
    const [y, m] = p.split("-").map(Number);
    return MONTHS[m - 1] + (short ? "" : " " + (y + 543));
  }
  function dateTime(iso) {
    if (!iso) return "";
    return new Date(iso).toLocaleString("th-TH", { day: "numeric", month: "short", year: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Bangkok" });
  }
  function dateShort(iso) {
    if (!iso) return "";
    return new Date(iso).toLocaleDateString("th-TH", { day: "numeric", month: "short", timeZone: "Asia/Bangkok" });
  }
  function baht(str) {
    if (str === null || str === undefined) return "—";
    const [i, f] = String(str).split(".");
    return "฿" + i.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (f && f !== "00" ? "." + f : "");
  }
  function currentPeriod() {
    const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Bangkok", year: "numeric", month: "2-digit" }).formatToParts(new Date());
    return parts.find((p) => p.type === "year").value + "-" + parts.find((p) => p.type === "month").value;
  }

  let toastTimer;
  function toast(msg) {
    let t = document.getElementById("toast");
    if (!t) { t = el("div", { id: "toast", class: "toast", role: "status" }); document.body.append(t); }
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
  }

  const SVG_NS = "http://www.w3.org/2000/svg";
  function icon(kind) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", "icon");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.8");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    const p = document.createElementNS(SVG_NS, "path");
    p.setAttribute("d", kind === "water" ? "M12 3c3 4 6 7.5 6 11a6 6 0 0 1-12 0c0-3.5 3-7 6-11z" : "M13 3 5 14h6l-1 7 8-11h-6z");
    svg.append(p);
    return svg;
  }

  window.UI = { el, api, periodLabel, dateTime, dateShort, baht, currentPeriod, toast, icon,
    TYPE: { water: "น้ำ", elec: "ไฟ" } };
})();
