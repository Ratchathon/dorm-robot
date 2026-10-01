(function () {
  "use strict";
  const form = document.getElementById("form");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button");
    btn.disabled = true;
    document.getElementById("err").textContent = "";
    try {
      await window.UI.api("/api/admin/login", { json: { password: document.getElementById("password").value } });
      location.href = "/admin";
    } catch (err) {
      document.getElementById("err").textContent = err.message;
      btn.disabled = false;
    }
  });
})();
