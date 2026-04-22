(function () {
  const md = document.getElementById("id_markdown");
  const preview = document.getElementById("preview");
  const form = document.getElementById("editor-form");
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
})();
