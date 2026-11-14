(function () {
  "use strict";
  function init() {
    const typeField = document.getElementById("id_notification_type");
    const editors = ["title_template", "body_template"].map(function (name) {
      return document.getElementById("id_" + name);
    }).filter(Boolean);
    if (!typeField || !editors.length) return;
    editors.forEach(function (textarea) {
      const wrapper = document.createElement("div");
      wrapper.style.margin = "8px 0";
      const select = document.createElement("select");
      select.setAttribute("aria-label", "انتخاب متغیر پیامک");
      select.style.maxWidth = "320px";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "button";
      button.textContent = "درج متغیر";
      button.style.marginInlineStart = "8px";
      wrapper.appendChild(select);
      wrapper.appendChild(button);
      textarea.parentNode.insertBefore(wrapper, textarea);
      function refresh() {
        let mapping = {};
        try { mapping = JSON.parse(textarea.getAttribute("data-sms-variables") || "{}"); } catch (_) {}
        const entries = mapping[typeField.value] || [];
        select.replaceChildren();
        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = "متغیر موردنظر را انتخاب کنید";
        select.appendChild(placeholder);
        entries.forEach(function (entry) {
          const option = document.createElement("option");
          option.value = entry.value;
          option.textContent = entry.label;
          select.appendChild(option);
        });
        button.disabled = entries.length === 0;
      }
      button.addEventListener("click", function () {
        if (!select.value) return;
        const token = "{{ " + select.value + " }}";
        textarea.setRangeText(token, textarea.selectionStart || 0, textarea.selectionEnd || 0, "end");
        textarea.focus();
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
      });
      typeField.addEventListener("change", refresh);
      refresh();
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
