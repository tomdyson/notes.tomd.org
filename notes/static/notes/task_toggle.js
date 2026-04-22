(function () {
  const body = document.querySelector(".note-body");
  if (!body) return;
  const toggleUrl = body.dataset.toggleUrl;
  if (!toggleUrl) return;

  function getCsrfToken() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    const input = document.querySelector("input[name=csrfmiddlewaretoken]");
    return input ? input.value : "";
  }

  const boxes = body.querySelectorAll('input[type="checkbox"][data-task-index]');
  boxes.forEach(function (box) {
    box.removeAttribute("disabled");
    box.style.cursor = "pointer";
    box.addEventListener("click", async function (e) {
      const idx = box.dataset.taskIndex;
      const previous = !box.checked;
      box.disabled = true;
      const fd = new FormData();
      fd.append("index", idx);
      try {
        const resp = await fetch(toggleUrl, {
          method: "POST",
          headers: { "X-CSRFToken": getCsrfToken() },
          body: fd,
          credentials: "same-origin",
        });
        if (!resp.ok) throw new Error(resp.statusText);
      } catch (err) {
        box.checked = previous;
      } finally {
        box.disabled = false;
      }
    });
  });
})();
