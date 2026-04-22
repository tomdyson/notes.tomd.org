(function () {
  const md = document.getElementById("id_markdown");
  const preview = document.getElementById("preview");
  const form = document.getElementById("editor-form");
  const footer = document.getElementById("editor-footer");
  if (!md || !preview || !form) return;

  let timer = null;
  function render() {
    const src = md.value;
    const html = window.marked.parse(src, { gfm: true, breaks: false });
    preview.innerHTML = window.DOMPurify.sanitize(html);
  }
  function schedule() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(render, 150);
  }
  md.addEventListener("input", schedule);
  render();

  document.addEventListener("keydown", function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key === "s") {
      e.preventDefault();
      form.submit();
    }
  });

  // Keep the form's bottom padding in sync with the footer height so
  // nothing is ever hidden behind it when the settings panel expands.
  function syncFooterPadding() {
    if (!footer) return;
    form.style.paddingBottom = footer.offsetHeight + 24 + "px";
  }
  syncFooterPadding();
  window.addEventListener("resize", syncFooterPadding);

  // Settings panel toggle (grows footer upwards).
  const settingsToggle = document.querySelector("[data-settings-toggle]");
  const settingsPanel = document.querySelector("[data-settings-panel]");
  if (settingsToggle && settingsPanel) {
    settingsToggle.addEventListener("click", function () {
      const open = !settingsPanel.hasAttribute("hidden");
      if (open) {
        settingsPanel.setAttribute("hidden", "");
        settingsToggle.setAttribute("aria-expanded", "false");
      } else {
        settingsPanel.removeAttribute("hidden");
        settingsToggle.setAttribute("aria-expanded", "true");
        const title = document.getElementById("id_title");
        if (title) title.focus();
      }
      syncFooterPadding();
    });
  }

  // Password reveal toggle (inside settings panel).
  const passwordToggle = document.querySelector("[data-password-toggle]");
  const passwordPanel = document.querySelector("[data-password-panel]");
  const passwordChevron = document.querySelector("[data-password-chevron]");
  if (passwordToggle && passwordPanel) {
    passwordToggle.addEventListener("click", function () {
      const open = !passwordPanel.hasAttribute("hidden");
      if (open) {
        passwordPanel.setAttribute("hidden", "");
      } else {
        passwordPanel.removeAttribute("hidden");
        const input = passwordPanel.querySelector('input[name="password"]');
        if (input) input.focus();
      }
      if (passwordChevron) {
        passwordChevron.textContent = open ? "▾" : "▴";
      }
      syncFooterPadding();
    });
  }

  // Write / Preview pane toggle.
  const paneToggle = document.querySelector("[data-pane-toggle]");
  if (paneToggle) {
    const buttons = paneToggle.querySelectorAll("[data-pane]");
    const panes = document.querySelectorAll("[data-pane-content]");
    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        const target = btn.dataset.pane;
        buttons.forEach(function (b) {
          const active = b === btn;
          b.setAttribute("aria-selected", active ? "true" : "false");
          b.classList.toggle("border-indigo-600", active);
          b.classList.toggle("text-stone-900", active);
          b.classList.toggle("border-transparent", !active);
          b.classList.toggle("text-stone-500", !active);
        });
        panes.forEach(function (p) {
          if (p.dataset.paneContent === target) {
            p.removeAttribute("hidden");
          } else {
            p.setAttribute("hidden", "");
          }
        });
        if (target === "preview") render();
      });
    });
  }
})();
