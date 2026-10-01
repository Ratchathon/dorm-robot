// Mobile burger menu state for the admin page (pure, tested with node --test).
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.NavMenu = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const CLOSERS = new Set(["select", "escape", "outside", "desktop"]);
  function nextMenuState(open, action) {
    if (action === "toggle") return !open;
    if (CLOSERS.has(action)) return false;
    return open;
  }
  function menuLabel(open) { return open ? "ปิดเมนู" : "เปิดเมนู"; }
  return { nextMenuState, menuLabel };
});
