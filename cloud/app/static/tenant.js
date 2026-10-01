(function () {
  "use strict";
  const { el, api, periodLabel, dateTime, baht, icon, toast, TYPE } = window.UI;
  const S = window.SummaryLogic;
  const token = location.pathname.split("/").pop();
  const base = "/api/tenant/" + encodeURIComponent(token);
  const app = document.getElementById("app");
  let data = null;
  let selected = null;

  const STATUS_TEXT = {
    missing: "ยังไม่ได้จดเดือนนี้",
    first: "ค่าแรกของมิเตอร์นี้ ใช้เป็นฐานของเดือนถัดไป",
    review: "ผู้ดูแลกำลังตรวจสอบเลขนี้",
    no_rate: "ผู้ดูแลยังไม่ได้ตั้งราคาต่อหน่วย",
  };

  function amountCard(kind, line) {
    const ok = line.status === "ok";
    return el("div", { class: "card" },
      el("span", { class: "k" }, icon(kind), "ค่า" + TYPE[kind]),
      el("span", { class: "v", text: ok ? baht(line.amount) : "—" }),
      el("span", { class: "d", text: ok ? line.units + " หน่วย × " + line.price + " บาท" : STATUS_TEXT[line.status] || "" }));
  }

  function photoCard(kind, line) {
    const caption = el("div", { class: "cap" },
      el("b", { text: TYPE[kind] + " · " + (line.prev_value ? line.prev_value + " → " : "") + (line.value || "—") }),
      el("span", { text: line.captured_at ? dateTime(line.captured_at) : "ยังไม่ได้จด" }));
    if (line.id && line.has_image) {
      const src = base + "/readings/" + line.id + "/image";
      return el("a", { class: "photo-card", href: src, target: "_blank", rel: "noopener", "aria-label": "ดูภาพมิเตอร์" + TYPE[kind] + "ขนาดเต็ม" },
        el("img", { src, alt: "ภาพมิเตอร์" + TYPE[kind], loading: "lazy" }), caption);
    }
    return el("div", { class: "photo-card" },
      el("div", { class: "ph", text: line.id ? "ผู้ดูแลบันทึกเอง (ไม่มีภาพ)" : "ยังไม่มีภาพ" }), caption);
  }

  function historyChart() {
    const months = data.periods.slice(0, 6).reverse();
    const vals = months.map((p) => (p.elec.status === "ok" ? p.elec.units : 0));
    const max = Math.max(1, ...vals);
    const bars = el("div", { class: "bars", role: "img", "aria-label": "หน่วยไฟย้อนหลัง " + months.length + " เดือน" });
    months.forEach((p, i) => {
      const bar = el("i");
      bar.style.height = Math.max(4, Math.round((vals[i] / max) * 90)) + "px";
      bars.append(el("div", { class: "col" + (p.period === selected ? " now" : "") },
        el("b", { text: p.elec.status === "ok" ? vals[i] : "–" }), bar, el("span", { text: periodLabel(p.period, true) })));
    });
    return el("section", { class: "card pad stack" },
      el("div", { class: "row" }, el("h2", { class: "grow", text: "ไฟย้อนหลัง" }), el("span", { class: "muted small", text: "หน่วย / เดือน" })), bars);
  }

  function disputeForm(p) {
    const msg = el("textarea", { class: "input", id: "msg", maxlength: "1000", placeholder: "เช่น เลขไฟในภาพคือ 3389 แต่ระบบบันทึก 3398" });
    const form = el("form", { class: "card pad stack", hidden: true },
      el("label", { for: "msg", class: "label", text: "อธิบายสิ่งที่ไม่ถูกต้อง (รอบ " + periodLabel(p.period) + ")" }), msg,
      el("button", { class: "btn primary", type: "submit", text: "ส่งให้ผู้ดูแล" }));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await api(base + "/disputes", { json: { period: p.period, message: msg.value } });
        toast("ส่งเรื่องให้ผู้ดูแลแล้ว");
        await load();
      } catch (err) { toast(err.message); }
    });
    const open = el("button", { class: "btn block", type: "button", text: "เลขไม่ตรงกับรูป? บอกผู้ดูแล",
      onclick: () => { form.hidden = false; open.hidden = true; msg.focus(); } });
    return [open, form];
  }

  function calcLink(p) {
    const params = new URLSearchParams({ mode: "meter", back: location.pathname });
    ["elec", "water"].forEach((k) => {
      const l = p[k];
      const price = l.price || (data.rates && data.rates[k]) || "";
      if (l.prev_value && l.value) params.set(k, [l.prev_value, l.value, price].join(","));
    });
    return el("a", { class: "btn dark block", href: "/calculator#" + params.toString(), text: "ลองคำนวณเอง" });
  }

  function render() {
    app.replaceChildren(el("header", { class: "t-head" },
      el("div", null, el("div", { class: "muted small", text: data.dorm_name }), el("h1", { text: "ห้อง " + data.room })),
      el("div", { class: "avatar", text: data.room })));

    if (!data.periods.length) {
      app.append(el("div", { class: "card pad muted", text: "ยังไม่มีการจดมิเตอร์ของห้องนี้" }),
        el("a", { class: "btn block", href: "/calculator", text: "เครื่องคำนวณค่าน้ำค่าไฟ" }));
      return;
    }
    const p = data.periods.find((x) => x.period === selected) || data.periods[0];
    selected = p.period;

    app.append(el("nav", { class: "chips scroll", "aria-label": "รอบเดือน", role: "tablist" },
      ...data.periods.map((x) => el("button", { class: "chip-btn", role: "tab", type: "button",
        "aria-selected": String(x.period === selected), text: periodLabel(x.period, x.period.slice(0, 4) === selected.slice(0, 4)),
        onclick: () => { selected = x.period; render(); } }))));

    const compare = S.compareMonth(data.periods, p.period, "elec");
    app.append(el("section", { class: "card summary hero" },
      el("span", { class: "k", text: "ค่าน้ำ + ค่าไฟ เดือน " + periodLabel(p.period) }),
      el("span", { class: "big", text: p.total ? baht(p.total) : "ยังไม่ครบ" }),
      compare ? el("span", { class: "pill", text: compare }) : null));

    app.append(el("div", { class: "split" }, amountCard("elec", p.elec), amountCard("water", p.water)));
    app.append(el("h2", { text: "รูปมิเตอร์จริง" }), el("div", { class: "photos" }, photoCard("elec", p.elec), photoCard("water", p.water)));
    if (data.periods.length > 1) app.append(historyChart());
    app.append(calcLink(p));

    data.disputes.filter((d) => d.period === p.period).forEach((d) => app.append(el("section", { class: "card pad stack" },
      el("div", { class: "row" }, el("span", { class: "pill " + (d.status === "resolved" ? "ok" : "accent"), text: d.status === "resolved" ? "ตอบแล้ว" : "รอผู้ดูแล" }),
        el("span", { class: "muted small", text: dateTime(d.created_at) })),
      el("div", { text: d.message }),
      d.reply ? el("div", { class: "note ok", text: "ผู้ดูแล: " + d.reply }) : null)));
    app.append(...disputeForm(p));
    app.append(el("div", { class: "muted small", text: "ลิงก์นี้เป็นของห้อง " + data.room + " เท่านั้น อย่าส่งต่อให้ผู้อื่น" }));
  }

  async function load() {
    try {
      data = await api(base);
      document.title = "ห้อง " + data.room + " · " + data.dorm_name;
      render();
    } catch (err) {
      app.replaceChildren(el("div", { class: "card pad stack" },
        el("h1", { text: "เปิดลิงก์ไม่ได้" }),
        el("div", { class: "muted", text: err.status === 404 ? "ลิงก์นี้ไม่ถูกต้องหรือถูกยกเลิกแล้ว ขอลิงก์ใหม่จากผู้ดูแลหอพัก" : "เชื่อมต่อไม่ได้ ลองใหม่อีกครั้ง" })));
    }
  }
  load();
})();
