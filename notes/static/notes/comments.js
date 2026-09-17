/* Anchored comments on the note page.
 *
 *  - Selecting text in the note shows a "Comment" button; choosing it fills
 *    the hidden selector fields of the new-comment form and shows a chip.
 *  - On load, every anchored comment is re-found in the rendered text via
 *    NoteAnchors and wrapped in <mark> elements; ones that no longer resolve
 *    are marked orphaned and get their "text has changed" badge shown.
 *  - Highlights and thread items link both ways (click to jump, hover to pair).
 *
 * Offsets are measured over the concatenated text nodes of .note-body,
 * skipping Mermaid diagrams (replaced by SVG at runtime), so the same text is
 * used when capturing a selection and when resolving it later.
 */
(function () {
  "use strict";

  var body = document.querySelector(".note-body");
  var section = document.getElementById("comments");
  var Anchors = window.NoteAnchors;
  if (!body || !section || !Anchors) return;

  var MAX_QUOTE = 2000; // matches the server-side cap
  var CHIP_CHARS = 120;

  // ---- text <-> DOM mapping ------------------------------------------------

  function isExcluded(node) {
    for (var el = node.parentElement; el && el !== body; el = el.parentElement) {
      if (el.classList.contains("mermaid")) return true;
    }
    return false;
  }

  function segments() {
    var walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        return isExcluded(node) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
      },
    });
    var segs = [];
    var pos = 0;
    var node;
    while ((node = walker.nextNode())) {
      segs.push({ node: node, start: pos, end: pos + node.data.length });
      pos += node.data.length;
    }
    return segs;
  }

  function textOf(segs) {
    return segs.map(function (s) { return s.node.data; }).join("");
  }

  // Global offsets of the part of a Range that lies inside the note, or null
  // if none of it does. A selection that runs past the note (a triple-click
  // on the last paragraph often does) is clamped to the note's text.
  function rangeToOffsets(range, segs) {
    var first = -1;
    var last = -1;
    for (var i = 0; i < segs.length; i++) {
      if (range.intersectsNode(segs[i].node)) {
        if (first === -1) first = i;
        last = i;
      }
    }
    if (first === -1) return null;
    var s = segs[first];
    var e = segs[last];
    return {
      start: range.startContainer === s.node ? s.start + range.startOffset : s.start,
      end: range.endContainer === e.node ? e.start + range.endOffset : e.end,
    };
  }

  function trimOffsets(text, off) {
    var start = off.start;
    var end = off.end;
    while (start < end && /\s/.test(text[start])) start++;
    while (end > start && /\s/.test(text[end - 1])) end--;
    return start < end ? { start: start, end: end } : null;
  }

  // Wrap the text between two global offsets in <mark>s, one per text node.
  function highlight(start, end, id, extraClass) {
    var marks = [];
    segments().forEach(function (seg) {
      if (seg.end <= start || seg.start >= end) return;
      var from = Math.max(start, seg.start) - seg.start;
      var to = Math.min(end, seg.end) - seg.start;
      if (to <= from || !seg.node.data.slice(from, to).trim()) return;
      var node = seg.node;
      if (to < node.data.length) node.splitText(to);
      if (from > 0) node = node.splitText(from);
      var mark = document.createElement("mark");
      mark.className = "comment-highlight" + (extraClass ? " " + extraClass : "");
      mark.dataset.commentId = id;
      node.parentNode.insertBefore(mark, node);
      mark.appendChild(node);
      marks.push(mark);
    });
    return marks;
  }

  function unwrap(marks) {
    marks.forEach(function (mark) {
      var parent = mark.parentNode;
      if (!parent) return;
      while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
      parent.removeChild(mark);
      parent.normalize();
    });
  }

  function marksFor(id) {
    return Array.prototype.slice.call(
      body.querySelectorAll('mark.comment-highlight[data-comment-id="' + id + '"]')
    );
  }

  // ---- pairing highlights with thread items ---------------------------------

  function setActive(id, on) {
    marksFor(id).forEach(function (m) { m.classList.toggle("is-active", on); });
    var li = document.getElementById("comment-" + id);
    if (li) li.classList.toggle("is-active", on);
  }

  var flashTimers = {};
  function flash(id) {
    setActive(id, true);
    clearTimeout(flashTimers[id]);
    flashTimers[id] = setTimeout(function () { setActive(id, false); }, 1600);
  }

  function pair(el, id) {
    el.addEventListener("mouseenter", function () { setActive(id, true); });
    el.addEventListener("mouseleave", function () { setActive(id, false); });
  }

  function jumpTo(el, id) {
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    flash(id);
  }

  // ---- resolve stored anchors ----------------------------------------------

  function resolveAll() {
    var text = textOf(segments());
    var resolved = [];
    section.querySelectorAll("li[data-quote]").forEach(function (li) {
      var offset = parseInt(li.dataset.offset, 10);
      var hit = Anchors.resolve(text, {
        quote: li.dataset.quote,
        prefix: li.dataset.prefix,
        suffix: li.dataset.suffix,
        offset: isNaN(offset) ? null : offset,
      });
      if (hit) {
        li.classList.add("is-anchored");
        resolved.push({ li: li, hit: hit });
      } else {
        li.classList.add("is-orphaned");
        var badge = li.querySelector("[data-orphan-badge]");
        if (badge) badge.hidden = false;
      }
    });
    resolved.forEach(function (r) {
      var id = r.li.dataset.commentId;
      highlight(r.hit.start, r.hit.end, id).forEach(function (mark) {
        pair(mark, id);
        mark.addEventListener("click", function () { jumpTo(r.li, id); });
      });
      pair(r.li, id);
      var quote = r.li.querySelector("[data-comment-quote]");
      if (quote) {
        quote.addEventListener("click", function () {
          var marks = marksFor(id);
          if (marks.length) jumpTo(marks[0], id);
        });
      }
    });
  }

  // ---- the new-comment form ------------------------------------------------

  var form = section.querySelector("form[data-comment-form]");
  var chip = form && form.querySelector("[data-anchor-chip]");
  var chipText = form && form.querySelector("[data-anchor-text]");
  var pendingMarks = [];

  function field(name) {
    return form.querySelector('input[type="hidden"][name="' + name + '"]');
  }

  function showChip(quote) {
    chipText.textContent = quote.length > CHIP_CHARS ? quote.slice(0, CHIP_CHARS - 1) + "…" : quote;
    chip.hidden = false;
  }

  function setAnchor(sel) {
    field("quote").value = sel.quote;
    field("prefix").value = sel.prefix;
    field("suffix").value = sel.suffix;
    field("start_offset").value = sel.start;
    showChip(sel.quote);
    unwrap(pendingMarks);
    pendingMarks = highlight(sel.start, sel.end, "pending", "is-pending");
    var composer = form.closest("[data-comment-composer]");
    if (composer) composer.open = true;
    form.scrollIntoView({ behavior: "smooth", block: "center" });
    var textarea = form.querySelector("textarea");
    if (textarea) textarea.focus({ preventScroll: true });
  }

  function clearAnchor() {
    ["quote", "prefix", "suffix", "start_offset"].forEach(function (name) { field(name).value = ""; });
    chip.hidden = true;
    unwrap(pendingMarks);
    pendingMarks = [];
  }

  // ---- selection popover ---------------------------------------------------

  var popover = document.createElement("button");
  popover.type = "button";
  popover.className = "comment-popover";
  popover.textContent = "Comment";
  popover.hidden = true;
  document.body.appendChild(popover);

  var pending = null;
  var mouseDown = false;
  var timer = null;

  function currentSelection() {
    var sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
    var range = sel.getRangeAt(0);
    var segs = segments();
    var off = rangeToOffsets(range, segs);
    if (!off) return null;
    var text = textOf(segs);
    off = trimOffsets(text, off);
    if (!off || off.end - off.start > MAX_QUOTE) return null;
    var ctx = Anchors.contextFor(text, off.start, off.end);
    return {
      start: off.start,
      end: off.end,
      quote: text.slice(off.start, off.end),
      prefix: ctx.prefix,
      suffix: ctx.suffix,
      rect: anchorRect(range),
    };
  }

  // The last line box of the selection that lies inside the note, so the
  // button sits by the end of what was selected rather than over a bounding
  // box that a triple-click stretches into the next block.
  function anchorRect(range) {
    var limit = body.getBoundingClientRect().bottom - 1;
    var rects = Array.prototype.filter.call(range.getClientRects(), function (r) {
      return r.width > 0 && r.height > 0 && r.top < limit;
    });
    return rects.length ? rects[rects.length - 1] : range.getBoundingClientRect();
  }

  function showPopover(sel) {
    popover.hidden = false;
    var r = sel.rect;
    var width = popover.offsetWidth;
    var top = window.scrollY + r.top - popover.offsetHeight - 8;
    if (r.top < popover.offsetHeight + 16) top = window.scrollY + r.bottom + 8;
    var left = window.scrollX + r.left + r.width / 2 - width / 2;
    var maxLeft = window.scrollX + document.documentElement.clientWidth - width - 8;
    left = Math.max(window.scrollX + 8, Math.min(left, maxLeft));
    popover.style.top = top + "px";
    popover.style.left = left + "px";
  }

  function hidePopover() {
    popover.hidden = true;
    pending = null;
  }

  function checkSelection() {
    if (mouseDown) return;
    var sel = currentSelection();
    if (!sel) { hidePopover(); return; }
    pending = sel;
    showPopover(sel);
  }

  document.addEventListener("selectionchange", function () {
    clearTimeout(timer);
    timer = setTimeout(checkSelection, 150);
  });
  document.addEventListener("mousedown", function (e) {
    if (e.target === popover) return;
    mouseDown = true;
  });
  document.addEventListener("mouseup", function () {
    mouseDown = false;
    clearTimeout(timer);
    timer = setTimeout(checkSelection, 0);
  });
  window.addEventListener("scroll", function () {
    if (pending) showPopover(pending);
  }, { passive: true });

  popover.addEventListener("mousedown", function (e) { e.preventDefault(); });
  popover.addEventListener("click", function () {
    if (!pending || !form) return;
    var sel = pending;
    hidePopover();
    window.getSelection().removeAllRanges();
    setAnchor(sel);
  });

  // ---- deleting: inline two-step instead of a native confirm() ------------

  function armDeleteForms() {
    section.querySelectorAll("form[data-confirm-delete]").forEach(function (form) {
      form.removeAttribute("onsubmit");
      var button = form.querySelector("button");
      var label = button.textContent;
      var cancel = document.createElement("button");
      cancel.type = "button";
      cancel.textContent = "cancel";
      cancel.className = "hover:text-stone-800";
      cancel.hidden = true;
      form.appendChild(cancel);
      var timer = null;

      function disarm() {
        clearTimeout(timer);
        form.dataset.armed = "";
        button.textContent = label;
        button.classList.remove("text-rose-700", "font-medium");
        cancel.hidden = true;
      }

      button.addEventListener("click", function (e) {
        if (form.dataset.armed) return; // second click submits normally
        e.preventDefault();
        form.dataset.armed = "1";
        button.textContent = "confirm delete";
        button.classList.add("text-rose-700", "font-medium");
        cancel.hidden = false;
        timer = setTimeout(disarm, 6000);
      });
      cancel.addEventListener("click", disarm);
    });
  }

  // Clicking a thread card opens its reply form without reserving a visible
  // action row. Interactive children keep their own click behaviour.
  function armReplyCards() {
    var threads = section.querySelectorAll("li.comment-thread");

    function openReply(thread) {
      threads.forEach(function (other) {
        var otherDetails = other.querySelector(":scope > [data-reply-control]");
        if (otherDetails && other !== thread) otherDetails.open = false;
      });
      var details = thread.querySelector(":scope > [data-reply-control]");
      if (details) details.open = true;
    }

    threads.forEach(function (thread) {
      thread.addEventListener("click", function (event) {
        if (event.target.closest("a, button, form, input, textarea, select, label, details")) return;
        var selection = window.getSelection();
        if (selection && !selection.isCollapsed) return;
        openReply(thread);
      });
      thread.addEventListener("keydown", function (event) {
        if (event.target !== thread || (event.key !== "Enter" && event.key !== " ")) return;
        event.preventDefault();
        openReply(thread);
        var textarea = thread.querySelector(":scope > [data-reply-control] textarea");
        if (textarea) textarea.focus();
      });
    });
  }

  function armNameEditors() {
    section.querySelectorAll("[data-name-field]").forEach(function (field) {
      var form = field.closest("form");
      var summary = form && form.querySelector("[data-name-summary]");
      var edit = summary && summary.querySelector("[data-name-edit]");
      var display = summary && summary.querySelector("[data-name-display]");
      var input = field.querySelector('input[name="name"]');
      var accept = field.querySelector("[data-name-accept]");
      var cancel = field.querySelector("[data-name-cancel]");
      if (!form || !summary || !edit || !display || !input || !accept || !cancel) return;

      function close() {
        field.hidden = true;
        summary.hidden = false;
      }

      edit.addEventListener("click", function () {
        summary.hidden = true;
        field.hidden = false;
        input.focus();
        input.select();
      });
      accept.addEventListener("click", function () {
        var name = input.value.trim();
        if (!name) {
          input.focus();
          return;
        }
        input.value = name;
        input.dataset.savedName = name;
        display.textContent = name;
        close();
      });
      cancel.addEventListener("click", function () {
        input.value = input.dataset.savedName;
        close();
      });
    });
  }

  // ---- boot ------------------------------------------------------------------

  armDeleteForms();
  armReplyCards();
  armNameEditors();

  resolveAll();

  if (form && chip) {
    form.querySelector("[data-anchor-clear]").addEventListener("click", clearAnchor);
    if (field("quote").value) {
      // Re-rendered after a failed submission: keep the selection visible.
      showChip(field("quote").value);
      var offset = parseInt(field("start_offset").value, 10);
      var hit = Anchors.resolve(textOf(segments()), {
        quote: field("quote").value,
        prefix: field("prefix").value,
        suffix: field("suffix").value,
        offset: isNaN(offset) ? null : offset,
      });
      if (hit) pendingMarks = highlight(hit.start, hit.end, "pending", "is-pending");
    }
  }

  var target = /^#comment-(\d+)$/.exec(window.location.hash);
  if (target) flash(target[1]);
})();
