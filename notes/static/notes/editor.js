(function () {
  const md = document.getElementById("id_markdown");
  const preview = document.getElementById("preview");
  const form = document.getElementById("editor-form");
  const footer = document.getElementById("editor-footer");
  if (!md || !preview || !form) return;

  let timer = null;
  let mermaidReady = false;

  function initMermaid() {
    if (!window.mermaid || mermaidReady) return;
    window.mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
    });
    mermaidReady = true;
  }

  function enhancePreview() {
    const mermaidBlocks = [];
    preview.querySelectorAll("pre > code.language-mermaid").forEach(function (code) {
      const diagram = document.createElement("div");
      diagram.className = "mermaid";
      diagram.textContent = code.textContent;
      code.parentElement.replaceWith(diagram);
      mermaidBlocks.push(diagram);
    });

    if (window.hljs) {
      preview.querySelectorAll("pre code").forEach(function (block) {
        if (!block.classList.contains("language-mermaid")) {
          window.hljs.highlightElement(block);
        }
      });
    }

    if (window.mermaid && mermaidBlocks.length) {
      initMermaid();
      window.mermaid.run({ nodes: mermaidBlocks }).catch(function () {});
    }
  }

  function render() {
    const src = md.value;
    if (!window.marked || !window.DOMPurify) {
      const fallback = document.createElement("pre");
      fallback.textContent = src;
      preview.replaceChildren(fallback);
      return;
    }
    const html = window.marked.parse(src, { gfm: true, breaks: false });
    preview.innerHTML = window.DOMPurify.sanitize(html);
    enhancePreview();
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

  // --- Image upload (paste / drop) ---
  function getCsrfToken() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    const input = form.querySelector("input[name=csrfmiddlewaretoken]");
    return input ? input.value : "";
  }

  function insertAtCaret(textarea, text) {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const before = textarea.value.substring(0, start);
    const after = textarea.value.substring(end);
    textarea.value = before + text + after;
    const newPos = start + text.length;
    textarea.selectionStart = textarea.selectionEnd = newPos;
    textarea.dispatchEvent(new Event("input"));
    return { start, end: newPos };
  }

  function replaceRange(textarea, start, end, text) {
    textarea.value =
      textarea.value.substring(0, start) + text + textarea.value.substring(end);
    textarea.dispatchEvent(new Event("input"));
  }

  let uploadCounter = 0;
  async function uploadImageFile(file) {
    const token = "up" + (++uploadCounter);
    const placeholder = `![uploading ${file.name || "image"}… ${token}]()`;
    const ins = insertAtCaret(md, placeholder);

    const fd = new FormData();
    fd.append("file", file);
    let replacement;
    try {
      const resp = await fetch("/upload/", {
        method: "POST",
        headers: { "X-CSRFToken": getCsrfToken() },
        body: fd,
        credentials: "same-origin",
      });
      if (!resp.ok) {
        let msg = resp.statusText;
        try {
          const body = await resp.json();
          if (body && body.error) msg = body.error;
        } catch (_) {}
        replacement = `*(upload failed: ${msg})*`;
      } else {
        const body = await resp.json();
        replacement = body.markdown;
      }
    } catch (e) {
      replacement = `*(upload failed: ${e.message || e})*`;
    }

    // Re-find the placeholder (user may have typed since) and swap it.
    const idx = md.value.indexOf(placeholder);
    if (idx === -1) return;
    replaceRange(md, idx, idx + placeholder.length, replacement);
  }

  function extractImageFiles(items) {
    const files = [];
    for (const item of items) {
      if (item.kind === "file" && item.type && item.type.startsWith("image/")) {
        const f = item.getAsFile();
        if (f) files.push(f);
      }
    }
    return files;
  }

  md.addEventListener("paste", function (e) {
    const items = e.clipboardData && e.clipboardData.items;
    if (!items) return;
    const files = extractImageFiles(items);
    if (!files.length) return;
    e.preventDefault();
    files.forEach(uploadImageFile);
  });

  md.addEventListener("dragover", function (e) {
    if (e.dataTransfer && Array.from(e.dataTransfer.types).includes("Files")) {
      e.preventDefault();
      md.classList.add("ring-2", "ring-indigo-400");
    }
  });
  md.addEventListener("dragleave", function () {
    md.classList.remove("ring-2", "ring-indigo-400");
  });
  md.addEventListener("drop", function (e) {
    md.classList.remove("ring-2", "ring-indigo-400");
    const dt = e.dataTransfer;
    if (!dt) return;
    const files = [];
    if (dt.items && dt.items.length) {
      for (const item of dt.items) {
        if (item.kind === "file" && item.type && item.type.startsWith("image/")) {
          const f = item.getAsFile();
          if (f) files.push(f);
        }
      }
    } else if (dt.files && dt.files.length) {
      for (const f of dt.files) {
        if (f.type && f.type.startsWith("image/")) files.push(f);
      }
    }
    if (!files.length) return;
    e.preventDefault();
    files.forEach(uploadImageFile);
  });

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
