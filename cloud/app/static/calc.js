// Exact money math for the calculator (BigInt satang, no floating-point drift).
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Calc = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // "1,234.50" -> "1234.5"; null when not a non-negative number with at most 4 decimals.
  function parseAmount(text) {
    if (typeof text !== "string") return null;
    const t = text.trim().replace(/,/g, "");
    const m = /^(\d+)(?:\.(\d{0,4}))?$/.exec(t);
    if (!m) return null;
    const frac = (m[2] || "").replace(/0+$/, "");
    const int = m[1].replace(/^0+(?=\d)/, "");
    return frac ? int + "." + frac : int;
  }

  function toScaled(dec) {
    const [i, f = ""] = dec.split(".");
    return { n: BigInt(i + f), scale: f.length };
  }

  // units x price, rounded half-up to satang (1/100 baht)
  function costSatang(units, price) {
    const a = toScaled(units), b = toScaled(price);
    const product = a.n * b.n;
    const scale = a.scale + b.scale;
    if (scale <= 2) return product * 10n ** BigInt(2 - scale);
    const div = 10n ** BigInt(scale - 2);
    return (product + div / 2n) / div;
  }

  function formatBaht(satang) {
    const baht = satang / 100n;
    const rest = (satang % 100n).toString().padStart(2, "0");
    return baht.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",") + "." + rest;
  }

  function unitsFromMeter(prev, curr) {
    if (!/^\d{1,8}$/.test(prev || "") || !/^\d{1,8}$/.test(curr || "")) return null;
    const diff = parseInt(curr, 10) - parseInt(prev, 10);
    if (diff >= 0) return { units: diff, rollover: false };
    const digits = Math.max(prev.length, curr.length);
    return { units: diff + Math.pow(10, digits), rollover: true };
  }

  // One meter line. mode "units": {units, price}; mode "meter": {prev, curr, price}
  function line(input) {
    const price = parseAmount(input.price || "");
    let units = null, rollover = false;
    if (input.mode === "meter") {
      const u = unitsFromMeter((input.prev || "").trim(), (input.curr || "").trim());
      if (u) { units = String(u.units); rollover = u.rollover; }
    } else {
      units = parseAmount(input.units || "");
    }
    if (units === null || price === null) return { ok: false, units, price, rollover };
    return { ok: true, units, price, rollover, satang: costSatang(units, price) };
  }

  return { parseAmount, costSatang, formatBaht, unitsFromMeter, line };
});
