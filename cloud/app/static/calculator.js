(function () {
  "use strict";
  const { icon } = window.UI;
  const C = window.Calc;
  const $ = (id) => document.getElementById(id);
  let mode = "units";

  document.querySelectorAll("[data-icon]").forEach((h) => h.prepend(icon(h.dataset.icon)));

  // Prefill from the tenant page: /calculator#mode=meter&elec=3312,3398,7&water=1207,1229,18&back=/r/xxx
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.get("mode") === "meter") mode = "meter";
  ["elec", "water"].forEach((k) => {
    const parts = (hash.get(k) || "").split(",");
    if (parts.length === 3) {
      $(k + "-prev").value = parts[0]; $(k + "-curr").value = parts[1]; $(k + "-price").value = parts[2];
    }
  });
  const back = hash.get("back");
  if (back && /^\/r\/[A-Za-z0-9_-]+$/.test(back)) { $("backLink").href = back; $("backLink").hidden = false; }
  if (hash.toString()) history.replaceState(null, "", location.pathname); // keep the room link out of history/bookmarks

  function setMode(m) {
    mode = m;
    document.querySelectorAll("[data-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === m)));
    document.querySelectorAll(".meter-only").forEach((e) => { e.hidden = m !== "meter"; });
    document.querySelectorAll(".units-only").forEach((e) => { e.hidden = m !== "units"; });
    render();
  }

  function render() {
    let sum = 0n, any = false;
    ["elec", "water"].forEach((k) => {
      const l = C.line({ mode, units: $(k + "-units").value, price: $(k + "-price").value,
        prev: $(k + "-prev").value, curr: $(k + "-curr").value });
      $(k + "-formula").textContent = l.ok ? l.units + " หน่วย × " + l.price + " บาท" : "กรอกให้ครบเพื่อดูผล";
      $(k + "-total").textContent = l.ok ? C.formatBaht(l.satang) + " บาท" : "—";
      const warn = $(k + "-warn");
      warn.hidden = !(l.ok && l.rollover);
      warn.textContent = "เลขเดือนนี้น้อยกว่าเดือนก่อน จึงคิดแบบมิเตอร์วนรอบ ถ้าไม่ใช่ ให้ตรวจเลขอีกครั้ง";
      if (l.ok) { sum += l.satang; any = true; }
    });
    $("grand").textContent = any ? C.formatBaht(sum) + " บาท" : "—";
  }

  document.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  document.querySelectorAll("input").forEach((i) => i.addEventListener("input", render));
  setMode(mode);
})();
